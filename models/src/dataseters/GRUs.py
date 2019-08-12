import os
import datetime as dt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

class TyDataset(Dataset):
    '''
    Typhoon dataset
    '''
    def __init__(self, args, train=True, train_num=None, transform=None):
        '''
        Args:
            ty_list (string): Path of the typhoon list file.
            radar_wrangled_data_folder (string): Folder of radar wrangled data.
            weather_wrangled_data_folder (string): Folder of weather wrangled data.
            ty_info_wrangled_data_folder (string): Folder of ty-info wrangled data.
            weather_list (list): A list of weather infos.
            train (boolean): Construct training set or not.
            train_num (int): The event number of training set.
            test_num (int): The event number of testing set.
            input_frames (int, 10-minutes-based): The frames of input data.
            target_frames (int, 10-minutes-based): The frames of output data.
            input_with_grid (boolean): The option to add gird info into input frames.
            transform (callable, optional): Optional transform to be applied on a sample.
        '''
        super().__init__()
        if args is not None:
            ty_list = pd.read_csv(args.ty_list, index_col='En name').drop('Ch name', axis=1)
            ty_list['Time of issuing'] = pd.to_datetime(ty_list['Time of issuing'])
            ty_list['Time of canceling'] = pd.to_datetime(ty_list['Time of canceling'])
            ty_list.index.name = 'Typhoon'
            
            self.ty_list = ty_list
            self.radar_folder = args.radar_folder
            self.radar_wrangled_data_folder = args.radar_wrangled_data_folder
            self.weather_wrangled_data_folder = args.weather_wrangled_data_folder
            self.ty_info_wrangled_data_folder = args.ty_info_wrangled_data_folder
            self.weather_list = args.weather_list
            self.input_with_grid = args.input_with_grid
            self.input_frames = args.input_frames
            self.target_frames = args.target_frames
            self.input_channels = args.input_channels
            self.I_x = args.I_x
            self.I_y = args.I_y
            self.I_shape = args.I_shape
            self.F_x = args.F_x
            self.F_y = args.F_y
            self.F_shape = args.F_shape
            self.O_shape = args.O_shape
            self.compression = args.compression
            self.target_RAD = args.target_RAD
            self.catcher_location = args.catcher_location

        self.transform = transform

        # set random seed
        np.random.seed(1)
        rand_tys = np.random.choice(len(ty_list), len(ty_list), replace=False)
        
        if train:
            if train_num is None:
                events_num = rand_tys[0:int(len(ty_list)/4*3)]
            else:
                assert train_num <= len(ty_list), 'The train_num shoud be less than total number of ty events.'
                events_num = rand_tys[0:train_num]
            self.events_list = self.ty_list.index[events_num]
        else:
            if train_num is None:
                events_num = rand_tys[int(len(ty_list)/4*3):]
            else:
                assert train_num <= len(ty_list), 'The train_num shoud be less than total number of ty events.'
                events_num = rand_tys[train_num:]
            self.events_list = self.ty_list.index[events_num]

        tmp = 0
        self.idx_df = pd.DataFrame([], columns=['The starting time', 'The ending time', 'The starting idx', 'The ending idx'], 
                                     index=self.events_list)
    
        for i in self.idx_df.index:
            frame_s = self.ty_list.loc[i, 'Time of issuing']
            frame_e = self.ty_list.loc[i, 'Time of canceling'] - dt.timedelta(minutes=(self.input_frames+self.target_frames-1)*10)
            
            self.total_frames = tmp + int((frame_e-frame_s).days*24*6 + (frame_e-frame_s).seconds/600) + 1
            self.idx_df.loc[i,:] = [frame_s, frame_e, tmp, self.total_frames-1]
            tmp = self.total_frames
        
        self.idx_df.index = self.events_list
        self.idx_df.index.name = 'Typhoon'

    def __len__(self):
        return self.total_frames

    def __getitem__(self, idx):
        # To identify which event the idx is in.
        assert idx < self.total_frames, 'Index is out of the range of the data!'

        for i in self.idx_df.index:
            if idx > self.idx_df.loc[i, 'The ending idx']:
                continue
            else:
                # print('idx:',idx)
                # determine some indexes
                tmp_idx = idx - self.idx_df.loc[i, 'The starting idx']

                # save current time
                current_time = dt.datetime.strftime(self.idx_df.loc[i,'The starting time']+dt.timedelta(minutes=10*(tmp_idx+self.input_frames-1)), format='%Y%m%d%H%M')
                
                # typhoon's name
                ty_name = str(self.idx_df.loc[i, 'The starting time'].year)+'.'+i

                # Input data(a tensor with shape (input_frames X C X H X W)) (0-5)
                input_data = np.zeros((self.input_frames, self.input_channels, self.I_shape[1], self.I_shape[0]), dtype=np.float32)
                # Radar Map(a tensor with shape (C X H X W)) last input image
                radar_map = np.zeros((self.input_channels, self.O_shape[1], self.O_shape[0]), dtype=np.float32)

                # Inputs-RAD
                for j in range(self.input_frames):
                    c = 0
                    file_time = dt.datetime.strftime(self.idx_df.loc[i,'The starting time']+dt.timedelta(minutes=10*(tmp_idx+j)), format='%Y%m%d%H%M')
                    data_path = os.path.join(self.radar_wrangled_data_folder, 'RAD', ty_name+'.'+file_time+'.pkl')
                    input_data[j,c,:,:] = pd.read_pickle(data_path, compression=self.compression).loc[self.I_y[0]:self.I_y[1], self.I_x[0]:self.I_x[1]].to_numpy()
                    c += 1

                    if self.input_with_grid:
                        gird_x, gird_y = np.meshgrid(np.arange(0, self.I_shape[0]), np.arange(0, self.I_shape[1]))
                        input_data[j,c,:,:] = gird_x
                        c += 1
                        input_data[j,c,:,:] = gird_y
                        c += 1

                # RADAR-MAP (last input image)
                c = 0
                file_time = dt.datetime.strftime(self.idx_df.loc[i,'The starting time']+dt.timedelta(minutes=10*(tmp_idx+self.input_frames-1)), format='%Y%m%d%H%M')
                data_path = os.path.join(self.radar_wrangled_data_folder, 'RAD', ty_name+'.'+file_time+'.pkl')
                radar_map[c,:,:] = pd.read_pickle(data_path, compression=self.compression).to_numpy()

                if self.input_with_grid:
                    gird_x, gird_y = np.meshgrid(np.arange(0, self.O_shape[0]), np.arange(0, self.O_shape[1]))
                    radar_map[c,:,:] = gird_x
                    c += 1
                    radar_map[c,:,:] = gird_y
                    c += 1
                
                # update index of time
                tmp_idx += self.input_frames

                # TYs-infos (6-24)
                data_path = os.path.join(self.ty_info_wrangled_data_folder, ty_name+'.csv')
                ty_infos = pd.read_csv(data_path)
                ty_infos.Time = pd.to_datetime(ty_infos.Time)
                ty_infos = ty_infos.set_index('Time')

                file_time1 = dt.datetime.strftime(self.idx_df.loc[i,'The starting time']+dt.timedelta(minutes=10*tmp_idx), format='%Y%m%d%H%M')
                file_time2 = dt.datetime.strftime(self.idx_df.loc[i,'The starting time']+dt.timedelta(minutes=10*(tmp_idx+self.target_frames-1)), format='%Y%m%d%H%M')
                
                ty_infos = ty_infos.loc[file_time1:file_time2,:].to_numpy()
                if self.catcher_location:
                    ty_infos = ty_infos[:,[0,1,-1]]
                else:
                    ty_infos = ty_infos[:,0:-1]
                
                # QPE data(a tensor with shape (target_frames X H X W)) (6-24)
                target_data = np.zeros((self.target_frames, self.F_shape[1], self.F_shape[0]), dtype=np.float32)
                if self.target_RAD:
                    datatype = 'RAD'
                else:
                    datatype = 'QPE'

                for j in range(self.target_frames):
                    file_time = dt.datetime.strftime(self.idx_df.loc[i,'The starting time']+dt.timedelta(minutes=10*(tmp_idx+j)), format='%Y%m%d%H%M')
                    data_path = os.path.join(self.radar_wrangled_data_folder, datatype, ty_name+'.'+file_time+'.pkl')
                    target_data[j,:,:] = pd.read_pickle(data_path, compression=self.compression).loc[self.F_y[0]:self.F_y[1], self.F_x[0]:self.F_x[1]].to_numpy()

                height = pd.read_pickle(os.path.join(self.radar_folder, 'height.pkl'), compression='bz2').loc[self.I_y[0]:self.I_y[1], self.I_x[0]:self.I_x[1]].to_numpy()

                height = (height-np.min(height))/(np.max(height)-np.min(height))

                self.sample = {'inputs': input_data, 'targets': target_data, 'ty_infos': ty_infos, 'radar_map': radar_map, 'current_time': current_time, 'height': height}
                
                if self.transform:
                    self.sample = self.transform(self.sample)

                # return the idx of sample
                return self.sample

class ToTensor(object):
    '''Convert ndarrays in samples to Tensors.'''
    def __call__(self, sample):
        return {'inputs': torch.from_numpy(sample['inputs']),
                'height': sample['height'], 
                'targets': torch.from_numpy(sample['targets']), 
                'ty_infos': torch.from_numpy(sample['ty_infos']),
                'radar_map': torch.from_numpy(sample['radar_map']),
                'current_time': sample['current_time']
                }

class Normalize(object):
    '''
    Normalize samples
    '''
    def __init__(self, args):
        assert type(args.max_values) == pd.Series or list, 'max_values is a not pd.series or list.'
        assert type(args.min_values) == pd.Series or list, 'min_values is a not pd.series or list.'
        self.max_values = args.max_values
        self.min_values = args.min_values
        self.normalize_target = args.normalize_target
        self.input_with_grid = args.input_with_grid
        self.target_RAD = args.target_RAD
        self.catcher_location = args.catcher_location
        self.I_shape = args.I_shape
        
    def __call__(self, sample):
        input_data, target_data, ty_infos, radar_map = sample['inputs'], sample['targets'], sample['ty_infos'], sample['radar_map'] 
        # normalize inputs
        index = 0
        input_data[:,index,:,:] = (input_data[:,index, :, :] - self.min_values['RAD']) / (self.max_values['RAD'] - self.min_values['RAD'])
        
        if self.input_with_grid:
            index += 1
            input_data[:,index,:,:] = input_data[:,index,:,:] / self.I_shape[0]
            index += 1
            input_data[:,index,:,:] = input_data[:,index,:,:] / self.I_shape[1]
        
        # normalize targets
        if self.normalize_target:
            if self.target_RAD:
                target_data = (target_data - self.min_values['RAD']) / (self.max_values['RAD'] - self.min_values['RAD'])
            else:
                target_data = (target_data - self.min_values['QPE']) / (self.max_values['QPE'] - self.min_values['QPE'])

        # normalize radar map
        index = 0
        radar_map[index,:,:] = (radar_map[index, :, :] - self.min_values['RAD']) / (self.max_values['RAD'] - self.min_values['RAD'])
        
        if self.input_with_grid:    
            index += 1
            radar_map[index,:,:] = radar_map[index,:,:] / self.I_shape[0]
            index += 1
            radar_map[index,:,:] = radar_map[index,:,:] / self.I_shape[1]

        # normalize ty info
        min_values = torch.from_numpy(self.min_values.loc['Lat':].to_numpy())
        max_values = torch.from_numpy(self.max_values.loc['Lat':].to_numpy())
        ty_infos = (ty_infos - min_values) / ( max_values - min_values)
        # numpy data: x_tsteps X H X W
        # torch data: x_tsteps X H X W
        return {'inputs': input_data, 'height': height, 'targets': target_data, 'ty_infos': ty_infos, 'radar_map': sample['radar_map'], 'current_time': sample['current_time']}
