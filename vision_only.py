import sys
import glob
import scipy.io as sio
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
import torchvision.models as models
from matplotlib import pyplot as plt
import numpy as np
import h5py
from PIL import Image
from sklearn.externals import joblib
import shutil
import os
import random
import pickle
import time
import gc
import re
from tensorboardX import SummaryWriter
import time
import math
from torchvision import datasets, models, transforms
import matplotlib.cm as cm
import cv2
import pandas as pd 
from sklearn.metrics import precision_score, recall_score, confusion_matrix, classification_report, accuracy_score, f1_score
from torch.utils.data import Dataset, DataLoader
from mosei_dataloader import mosei

torch.manual_seed(777)
torch.cuda.manual_seed(777)
np.random.seed(777)

preprocess = transforms.Compose([
	transforms.ToTensor(),
	transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

'---------------------------------------------------LSTM VisualNet-------------------------------------------------------'

class VisionNet(nn.Module):
	def __init__(self,input_size,hidden_size,num_layers):
		super(VisionNet, self).__init__()
		self.lstm = nn.LSTM(input_size,hidden_size,num_layers,bidirectional=True)


	def forward(self,x):
		x = torch.transpose(x,0,1)
		hiddens,_ = self.lstm(x)
		return hiddens[-1]


'---------------------------------------------------Memory to Emotion Decoder------------------------------------------'
class predictor(nn.Module):
	def __init__(self,no_of_emotions,input_size):
		super(predictor, self).__init__()
		self.fc = nn.Linear(input_size, no_of_emotions)

	def forward(self,x):
		x = self.fc(x)
		return x
'------------------------------------------------------Hyperparameters-------------------------------------------------'
batch_size = 1
mega_batch_size = 1
no_of_emotions = 6

use_CUDA = True
use_pretrained = True
num_workers = 20

test_mode = True
val_mode = False
train_mode = False

no_of_epochs = 12
vision_input_size = 35 # Dont Change
vision_num_layers = 2
vision_hidden_size = 512
predictor_input_size = 1024 
'----------------------------------------------------------------------------------------------------------------------'
Vision_encoder = VisionNet(vision_input_size, vision_hidden_size, vision_num_layers)
Predictor = predictor(no_of_emotions,predictor_input_size)
if train_mode:
	train_dataset = mosei(mode= "train")
	data_loader = torch.utils.data.DataLoader(dataset=train_dataset,
                                        batch_size=batch_size,
                                        shuffle=True,num_workers = num_workers)
elif val_mode:
	val_dataset = mosei(mode = "val")
	data_loader = torch.utils.data.DataLoader(dataset=val_dataset,
                                        batch_size=1,
                                        shuffle=False,num_workers = num_workers)
	no_of_epochs = 1
else:
	test_dataset = mosei(mode = "test")
	data_loader = torch.utils.data.DataLoader(dataset=test_dataset,
                                        batch_size=1,
                                        shuffle=False,num_workers = num_workers)
	no_of_epochs = 1
curr_epoch = 0
total = 0
'----------------------------------------------------------------------------------------------------------------------'
Vision_encoder = Vision_encoder.cuda()
Predictor = Predictor.cuda()
'----------------------------------------------------------------------------------------------------------------------'
criterion = nn.MSELoss(size_average = False)
params = list(Vision_encoder.parameters()) + list(Predictor.parameters())
print('Parameters in the model = ' + str(len(params)))
optimizer = torch.optim.Adam(params, lr = 0.0001)
# optimizer = torch.optim.SGD(params, lr =0.001,momentum = 0.9 )

'------------------------------------------Saving Intermediate Models--------------------------------------------------'


def save_checkpoint(state, is_final, filename='vision_net'):
	filename = filename +'_'+str(state['epoch'])+'.pth.tar'
	os.system("mkdir -p vision_only") 
	torch.save(state, './vision_only/'+filename)
	if is_final:
		shutil.copyfile(filename, 'model_final.pth.tar')


'-------------------------------------------Setting into train mode----------------------------------------------------'

if not train_mode:
	Vision_encoder.train(False)
	Predictor.train(False)
else:
	Vision_encoder.train(True)
	Predictor.train(True)

'----------------------------------------------------------------------------------------------------------------------'
epoch = 0
y_true = []
y_pred = []
while epoch<no_of_epochs:
	j_start = 0
	running_loss = 0
	running_corrects = 0
	if use_pretrained:
		# pretrained_file = './vision_only/vision_net_iter_8000_0.pth.tar'
		pretrained_file = './vision_only/vision_net__11.pth.tar'

		checkpoint = torch.load(pretrained_file)
		Vision_encoder.load_state_dict(checkpoint['Vision_encoder'])
		Predictor.load_state_dict(checkpoint['Predictor'])
		use_pretrained = False
		if train_mode:
			epoch = checkpoint['epoch']+1
			optimizer.load_state_dict(checkpoint['optimizer'])

	K = 0
	for i,(vision,vocal,emb,gt) in enumerate(data_loader):
		if use_CUDA:
			vision = Variable(vision.float()).cuda()
			gt = Variable(gt.float()).cuda()

		vision_output = Vision_encoder(vision)
		outputs = Predictor(vision_output)
		outputs = torch.clamp(outputs,0,3)
		loss = criterion(outputs, gt)
		if train_mode and K%mega_batch_size==0:
			loss.backward()
			optimizer.step()
			optimizer.zero_grad()
			Vision_encoder.zero_grad()
			Predictor.zero_grad()

		# outputs_ = Variable(torch.FloatTensor([ 0.1565 ,0.1233,  0.0401,  0.4836 , 0.1596,  0.04842])).cuda()
		# loss = criterion(outputs_, gt)

		running_loss += loss.data[0]
		K+=1
		average_loss = running_loss/K
		if train_mode and K%mega_batch_size==0:			
			print('Training -- Epoch [%d], Sample [%d], Average Loss: %.4f'
			% (epoch+1, K, average_loss))
		elif val_mode:
			print('Validating -- Epoch [%d], Sample [%d], Average Loss: %.4f'
			% (epoch+1, K, average_loss))
		elif test_mode:
			print('Testing -- Epoch [%d], Sample [%d], Average Loss: %.4f'
			 % (epoch+1, K, average_loss))

		if train_mode:
			if K%4000==0:
				save_checkpoint({
					'epoch': epoch,
					'loss' : running_loss,
					'j_start' : 0,
					'Vision_encoder' : 	Vision_encoder.state_dict(),
					'Predictor' : Predictor.state_dict(),
					'optimizer': optimizer.state_dict(),
				}, False,'vision_net_iter_'+str(K))
	'-------------------------------------------------Saving model after every epoch-----------------------------------'
	if train_mode:
		save_checkpoint({
			'epoch': epoch,
			'loss' : running_loss,
			'j_start' : 0,
			'Vision_encoder' : 	Vision_encoder.state_dict(),
			'Predictor' : Predictor.state_dict(),
			'optimizer': optimizer.state_dict(),
		}, False,'vision_net_')
	epoch+= 1 
'------------------------------------------------------Saving model after training completion--------------------------'
if train_mode:
	save_checkpoint({
		'epoch': epoch,
		'loss' : running_loss,
		'j_start' : 0,
		'Vision_encoder' : 	Vision_encoder.state_dict(),
		'Predictor' : Predictor.state_dict(),
		'optimizer': optimizer.state_dict(),
	}, False)

# print('Accuracy:', accuracy_score(y_true, y_pred))
# print('F1 score:', f1_score(y_true, y_pred,average = 'weighted'))
# print('Recall:', recall_score(y_true, y_pred,average ='weighted'))
# print('Precision:', precision_score(y_true, y_pred,average = 'weighted'))
