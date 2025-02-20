import cv2
import os

'''
train where the train data is build somewhere and you are pointing to it

 python main.py --ep 1 --to 200 --bs 18 --lr 0.0001 --sample 65536 --data ../Data --test_image 0016.png

testing on the data

python main.py --test_only True --gpu 1 --chk 159 --scale 2 --test_image some.png

use the above to run the file. this is the orinal configuration as per the paper

'''

import argparse
parser = argparse.ArgumentParser(description='control RDNSR')
parser.add_argument('--to', action="store",dest="tryout", default=200)
parser.add_argument('--ep', action="store",dest="epochs", default=1000)
parser.add_argument('--bs', action="store",dest="batch_size", default=16)
parser.add_argument('--lr', action="store",dest="learning_rate", default=0.0001)
parser.add_argument('--gpu', action="store",dest="gpu", default=-1)
parser.add_argument('--chk',action="store",dest="chk",default=-1)
parser.add_argument('--sample',action='store',dest="sample",default=512)
# parser.add_argument('--test_sample', action="store",dest="test_sample",default=190)
# parser.add_argument('--scale', action='store' , dest = 'scale' , default = 2)
parser.add_argument('--data', action='store' , dest = 'folder' , default = '../Data')
parser.add_argument('--test_image', action = 'store' , dest = 'test_image' , default = 'test.png')
parser.add_argument('--test_only' , action = 'store', dest = 'test_only' , default = False)
parser.add_argument('--zoom',action='store',dest = 'zoom' , default = False)

values = parser.parse_args()
learning_rate = float(values.learning_rate)
batch_size = int(values.batch_size)
epochs = int(values.epochs)
tryout = int(values.tryout)
gpu=int(values.gpu)
sample = int(values.sample)
# test_sample = int(values.test_sample)
# scale = int(values.scale)
folder = values.folder
test_only = values.test_only
chk = int(values.chk)
zoom = values.zoom

if gpu >= 0:
    os.environ["CUDA_VISIBLE_DEVICES"]=str(gpu)



import sys
import numpy as np
import matplotlib.pyplot as plt
from SRIP_DATA_BUILDER import DATA
from keras.models import Model
from keras.layers import Input,MaxPool2D,SeparableConv2D,Deconvolution2D,Conv2DTranspose ,Convolution2D , Add, Dense , AveragePooling2D , UpSampling2D , Reshape , Flatten , Subtract , Concatenate
from keras.optimizers import Adam
from keras.callbacks import LearningRateScheduler
from keras import backend as k

from keras.utils import multi_gpu_model

import tensorflow as tf
from keras.utils import plot_model
from subpixel import Subpixel
from PIL import Image
import cv2




def PSNRLossnp(y_true,y_pred):
        return 10* np.log(255*2 / (np.mean(np.square(y_pred - y_true))))

def SSIM( y_true,y_pred):
    u_true = k.mean(y_true)
    u_pred = k.mean(y_pred)
    var_true = k.var(y_true)
    var_pred = k.var(y_pred)
    std_true = k.sqrt(var_true)
    std_pred = k.sqrt(var_pred)
    c1 = k.square(0.01*7)
    c2 = k.square(0.03*7)
    ssim = (2 * u_true * u_pred + c1) * (2 * std_pred * std_true + c2)
    denom = (u_true ** 2 + u_pred ** 2 + c1) * (var_pred + var_true + c2)
    return ssim / denom

def PSNRLoss(y_true, y_pred):
        return 10* k.log(255**2 /(k.mean(k.square(y_pred - y_true))))


class SRResnet:
    def L1_loss(self , y_true , y_pred):
        return k.mean(k.abs(y_true - y_pred))
    
    #def L1_plus_PSNR_loss(self,y_true, y_pred):
        #return self.L1_loss(y_true , y_pred) - 0.0001*PSNRLoss(y_true , y_pred)
    
    def RDBlocks(self,x,name , count = 6 , g=32):
        ## 6 layers of RDB block
        ## this thing need to be in a damn loop for more customisability
        li = [x]
        pas = Convolution2D(filters=g, kernel_size=(3,3), strides=(1, 1), padding='same' , activation='relu' , name = name+'_conv1')(x)
        for i in range(2 , count+1):
            li.append(pas)
            out =  Concatenate(axis = self.channel_axis)(li) # conctenated out put
            pas = Convolution2D(filters=g, kernel_size=(3,3), strides=(1, 1), padding='same' , activation='relu', name = name+'_sep_conv'+str(i))(out)
            
        # feature extractor from the dense net
        li.append(pas)
        out = Concatenate(axis = self.channel_axis)(li)
        feat = Convolution2D(filters=64, kernel_size=(1,1), strides=(1, 1), padding='same',activation='relu' , name = name+'_Local_Conv')(out)
        
        feat = Add()([feat , x])
        return feat
        
    def visualize(self):
        plot_model(self.inference_model, to_file='model.png' , show_shapes = True)
    
    def get_model(self):
        return self.inference_model

    def get_RDN_pass(self, x , scale , depth=3 ):
        pass1 = Convolution2D(filters=64, kernel_size=(3,3), strides=(1, 1), padding='same' , activation='relu')(x)
        pass2 = Convolution2D(filters=64, kernel_size=(3,3), strides=(1, 1), padding='same' , activation='relu')(pass1)

        
        RDB = self.RDBlocks(pass2 , 'RDB1_'+str(scale))
        RDBlocks_list = [RDB,]
        for i in range(2,depth+1):
            RDB = self.RDBlocks(RDB ,'RDB'+str(i)+'_'+str(scale))
            RDBlocks_list.append(RDB)
        out = Concatenate(axis = self.channel_axis)(RDBlocks_list)
        out = Convolution2D(filters=64 , kernel_size=(1,1) , strides=(1,1) , padding='same')(out)
        out = Convolution2D(filters=64 , kernel_size=(3,3) , strides=(1,1) , padding='same')(out)
        output = Add()([out , pass1])
        output = Conv2DTranspose(filters=64 , kernel_size=3  , strides=(2,2), padding='same')(output)
        output = Convolution2D(filters =3 , kernel_size=(3,3) , strides=(1 , 1) , padding='same' , name='output'+str(scale)+'x')(output)
        return output
    
    def __init__(self , channel = 3 , lr=0.0001 , patch_size=32 ,chk = -1 , test = False):
        self.channel_axis = 3
        self.patch_size = patch_size

        inp = Input(shape = (patch_size , patch_size , channel))

        zoom2x = self.get_RDN_pass(depth = 6 , x = inp , scale = 2)
        zoom4x = self.get_RDN_pass(depth = 6 , x = zoom2x , scale = 4)
        zoom8x = self.get_RDN_pass(depth = 6 , x = zoom4x , scale = 8)


        model = Model(inputs=inp , outputs = [zoom2x, zoom4x , zoom8x])
        adam = Adam(lr=lr, beta_1=0.9, beta_2=0.999, epsilon=None, decay=lr/2, amsgrad=False)
        
        # # multi gpu setting

        if chk >=0 :
            print("loading existing weights !!!")
            model.load_weights('model_iter'+str(chk)+'.h5')
        
        self.inference_model = model

        if gpu < 0:
            print("Running in multi gpu mode expecting 3 gpus , check source code")
            self.multi_gpu_model = multi_gpu_model(model, gpus=3)
        # # Modification of adding PSNR as a loss factor
        if not test:
            self.multi_gpu_model.compile(loss={'output2x':self.L1_loss , 'output4x':self.L1_loss , 'output8x':self.L1_loss }, optimizer=adam , metrics=[PSNRLoss])
        
        
            
    def fit(self , x , x2 , x4 , x8 ,batch_size=16 , epoch = 1000 ):
        # with tf.device('/gpu:'+str(gpu)):    
        hist = self.multi_gpu_model.fit(x = x ,y = {'output2x':x2 , 'output4x':x4 , 'output8x':x8},  batch_size = batch_size , verbose =1 , nb_epoch=epoch)
        return hist.history


if __name__ == '__main__':
    CHANNEL = 3
    out_patch_size =  256
    inp_patch_size = 32
    DATA = DATA(folder = folder , patch_size = out_patch_size)
    if not test_only:
        DATA.load_data(folder=folder)
        x = DATA.training_patches_8x
        x2 = DATA.training_patches_4x
        x4 = DATA.training_patches_2x
        x8 = DATA.training_patches_Y

    net = SRResnet(lr = learning_rate , chk = chk , test = test_only)
    if not test_only:
        net.visualize()
        net.get_model().summary()

    image_name = values.test_image

    try:
        img = cv2.imread(image_name)
        img = cv2.cvtColor(img , cv2.COLOR_BGR2RGB)
    except cv2.error as e:
        print("Bad image path check the name or path !!")
        exit()

    if not zoom:
        R = DATA.patch_size - img.shape[0] % DATA.patch_size
        C = DATA.patch_size - img.shape[1] % DATA.patch_size

        img = np.pad(img, [(0,R),(0,C),(0,0)] , 'constant')

        Image.fromarray(img).save("test_image_padded.png")

        lr_2x_img = cv2.resize(img , (int(img.shape[1]/2),int(img.shape[0]/2)) ,cv2.INTER_CUBIC)
        Image.fromarray(lr_2x_img).save("test_2x_lr_padded.png")

        lr_4x_img = cv2.resize(img , (int(img.shape[1]/4),int(img.shape[0]/4)) ,cv2.INTER_CUBIC)
        Image.fromarray(lr_4x_img).save("test_4x_lr_padded.png")

        lr_8x_img = cv2.resize(img , (int(img.shape[1]/8),int(img.shape[0]/8)) ,cv2.INTER_CUBIC)
        Image.fromarray(lr_8x_img).save("test_8x_lr_padded.png")                

        p , r , c = DATA.patchify(lr_8x_img,scale=8) 

        if not os.path.isdir('Results'):
            os.mkdir('Results')	

    if not test_only:
        for i in range(chk+1,tryout):
            print("tryout no: ",i)   
            
            samplev = np.random.random_integers(0 , x.shape[0]-1 , sample)
            net.fit(x[samplev] , x2[samplev] , x4[samplev] , x8[samplev] , batch_size , epochs )
            
            
            net.get_model().save_weights('model_iter'+str(i)+'.h5')
            g = net.get_model().predict(np.array(p))
            gen2x = DATA.reconstruct(g[0] , r , c , scale=4)
            gen4x = DATA.reconstruct(g[1] , r , c , scale=2)
            gen8x = DATA.reconstruct(g[2] , r , c , scale=1)
            d = 'Results/'+str(i)
            if not os.path.isdir(d):
                os.mkdir(d)
            Image.fromarray(gen2x).save(d+"/test_2x_gen_.png")
            Image.fromarray(gen4x).save(d+"/test_4x_gen_.png")
            Image.fromarray(gen8x).save(d+"/test_8x_gen_.png")
            print("Reconstruction Gain:", PSNRLossnp(img , gen8x))
    else :
        if zoom:
            gz , r2 , c2 = DATA.patchify(img , scale = 8)
            gz = net.get_model().predict(np.array(gz))[2]		
            genz = DATA.reconstruct(gz , r2 , c2 , scale = 1)
            Image.fromarray(genz).save("test_image_zoomed_8x.png")		
        else:
            g = net.get_model().predict(np.array(p))[2]
            gen = DATA.reconstruct(g , r , c , scale=1)		
            Image.fromarray(gen).save("test_8x_gen_.png")
            print("Reconstruction Gain:", PSNRLossnp(img , gen))
