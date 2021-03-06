import os
import copy
import cv2
import numpy as np

import torch
from torch.autograd import Variable
from torchvision import models,datasets,transforms
from torch.nn import functional as F

from customization import loadModel

def convert_to_grayscale(cv2im):
    grayscale_im = np.sum(np.abs(cv2im), axis=0)
    im_max = np.percentile(grayscale_im, 99)
    im_min = np.min(grayscale_im)
    grayscale_im = (np.clip((grayscale_im - im_min) / (im_max - im_min), 0, 1))
    grayscale_im = np.expand_dims(grayscale_im, axis=0)
    return grayscale_im


def save_gradient_images(gradient, file_name):
    """
        Exports the original gradient image

    Args:
        gradient (np arr): Numpy array of the gradient with shape (3, 224, 224)
        file_name (str): File name to be exported
    """
    if not os.path.exists('results'):
        os.makedirs('results')
    gradient = gradient - gradient.min()
    gradient /= gradient.max()
    gradient = np.uint8(gradient * 255).transpose(1, 2, 0)
    path_to_file = os.path.join('results', file_name + '.jpg')
    # Convert RBG to GBR
    gradient = gradient[..., ::-1]
    cv2.imwrite(path_to_file, gradient)
    return gradient


def save_class_activation_on_image(network, org_img, activation_map, file_name):
    """
        Saves cam activation map and activation map on the original image

    Args:
        org_img (PIL img): Original image
        activation_map (numpy arr): activation map (grayscale) 0-255
        file_name (str): File name of the exported image
    """
    if not os.path.exists('results'):
        os.makedirs('results')
    # Grayscale activation map
    path_to_file = os.path.join('results', file_name+'_Cam_Grayscale.jpg')
    cv2.imwrite(path_to_file, activation_map)
    # Heatmap of activation map
    activation_heatmap = cv2.applyColorMap(activation_map, cv2.COLORMAP_HSV)
    path_to_file = os.path.join('results', file_name+'_Cam_Heatmap.jpg')
    cv2.imwrite(path_to_file, activation_heatmap)
    # Heatmap on picture
    if network == 'Custom':
        org_img = cv2.resize(org_img, (32, 32))
    else:
        org_img = cv2.resize(org_img, (224, 224))
    img_with_heatmap = np.float32(activation_heatmap) + np.float32(org_img)
    img_with_heatmap = img_with_heatmap / np.max(img_with_heatmap)
    path_to_file = os.path.join('results', file_name+'_Cam_On_Image.jpg')
    cv2.imwrite(path_to_file, np.uint8(255 * img_with_heatmap))
    return activation_map, activation_heatmap, np.uint8(255 * img_with_heatmap)

def preprocess_image(cv2im, resize_im=True):
    """
        Processes image for CNNs

    Args:
        PIL_img (PIL_img): Image to process
        resize_im (bool): Resize to 224 or not
    returns:
        im_as_var (Pytorch variable): Variable that contains processed float tensor
    """
    # mean and std list for channels (Imagenet)
    mean = [0.485, 0.456, 0.406]
    std = [0.229, 0.224, 0.225]
    # Resize image
    if resize_im:
        cv2im = cv2.resize(cv2im, (224, 224))
    im_as_arr = np.float32(cv2im)
    im_as_arr = np.ascontiguousarray(im_as_arr[..., ::-1])
    im_as_arr = im_as_arr.transpose(2, 0, 1)  # Convert array to D,W,H
    # Normalize the channels
    for channel, _ in enumerate(im_as_arr):
        im_as_arr[channel] /= 255
        im_as_arr[channel] -= mean[channel]
        im_as_arr[channel] /= std[channel]
    # Convert to float tensor
    im_as_ten = torch.from_numpy(im_as_arr).float()
    # Add one more channel to the beginning. Tensor shape = 1,3,224,224
    im_as_ten.unsqueeze_(0)
    # Convert to Pytorch variable
    im_as_var = Variable(im_as_ten, requires_grad=True)
    return im_as_var


def recreate_image(im_as_var):
    """
        Recreates images from a torch variable, sort of reverse preprocessing

    Args:
        im_as_var (torch variable): Image to recreate

    returns:
        recreated_im (numpy arr): Recreated image in array
    """
    reverse_mean = [-0.485, -0.456, -0.406]
    reverse_std = [1/0.229, 1/0.224, 1/0.225]
    recreated_im = copy.copy(im_as_var.data.numpy()[0])
    for c in range(3):
        recreated_im[c] /= reverse_std[c]
        recreated_im[c] -= reverse_mean[c]
    recreated_im[recreated_im > 1] = 1
    recreated_im[recreated_im < 0] = 0
    recreated_im = np.round(recreated_im * 255)

    recreated_im = np.uint8(recreated_im).transpose(1, 2, 0)
    # Convert RBG to GBR
    recreated_im = recreated_im[..., ::-1]
    return recreated_im


def get_positive_negative_saliency(gradient):
    """
        Generates positive and negative saliency maps based on the gradient
    Args:
        gradient (numpy arr): Gradient of the operation to visualize

    returns:
        pos_saliency ( )
    """
    pos_saliency = (np.maximum(0, gradient) / gradient.max())
    neg_saliency = (np.maximum(0, -gradient) / -gradient.min())
    return pos_saliency, neg_saliency


def get_params(example_index,network,isTrained,training='Normal', structure=''):
    """
        Gets used variables for almost all visualizations, like the image, model etc.

    Args:
        example_index (int): Image id to use from examples

    returns:
        original_image (numpy arr): Original image read from the file
        prep_img (numpy_arr): Processed image
        target_class (int): Target class for the image
        file_name_to_export (string): File name to export the visualizations
        pretrained_model(Pytorch model): Model to use for the operations
    """

    if network == 'Custom':
        if training == 'Normal':
            transform_test = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
            ])

            testset = datasets.CIFAR10(root='./customization/data', train=False, download=False, transform=transform_test)
            testloader = torch.utils.data.DataLoader(testset, batch_size=1, shuffle=True, num_workers=2)
            classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')

            prep_img, target_class= next(iter(testloader))
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            prep_img,target_class = prep_img.to(device),target_class.to(device)

            file_name_to_export = classes[target_class]
            target_class = target_class.cpu().numpy()
            original_image = prep_img.cpu().numpy().transpose(0,2,3,1)[0,:,:,:]
            mean = np.array([0.4914, 0.4822, 0.4465])
            std = np.array([0.2023, 0.1994, 0.2010])
            original_image = std * original_image + mean
            original_image = np.clip(original_image, 0, 1)
            #################################################
            prep_img = Variable(prep_img, requires_grad=True)
            #################################################
        elif training == 'Adversarial':
            transform_test = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
            ])

            testset = datasets.CIFAR10(root='./customization/data', train=False, download=False,
                                       transform=transform_test)
            testloader = torch.utils.data.DataLoader(testset, batch_size=1, shuffle=True, num_workers=2)
            classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')

            prep_img, target_class = next(iter(testloader))
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            prep_img, target_class = prep_img.to(device), target_class.to(device)

            file_name_to_export = classes[target_class]
            target_class = target_class.cpu().numpy()
            original_image = prep_img.cpu().numpy().transpose(0, 2, 3, 1)[0, :, :, :]
            #mean = np.array([0.4914, 0.4822, 0.4465])
            #std = np.array([0.2023, 0.1994, 0.2010])
            #original_image = std * original_image + mean
            #original_image = np.clip(original_image, 0, 1)
            #################################################
            prep_img = Variable(prep_img, requires_grad=True)
            #################################################
    else:
        # Pick one of the examples
        example_list = [['input_images/snake.jpg', 56],
                        ['input_images/cat_dog.png', 243],
                        ['input_images/spider.png', 72],
                        ['input_images/volcano.jpg', 980],
                        ['input_images/pelican.jpg', 144],
                        ['input_images/jellyfish.jpg', 107],
                        ['input_images/admiral.jpg', 321]]

        selected_example = example_index
        img_path = example_list[selected_example][0]
        target_class = example_list[selected_example][1]
        file_name_to_export = img_path[img_path.rfind('/')+1:img_path.rfind('.')]
        # Read image
        original_image = cv2.imread(img_path, 1)
        # Process image
        prep_img = preprocess_image(original_image)

    # Define model
    if network == "AlexNet":
        pretrained_model = models.alexnet(pretrained=isTrained)
        pretrained_model.eval()
    elif network =="VGG19":
        pretrained_model = models.vgg19(pretrained = isTrained)
        pretrained_model.eval()
    elif network =="ResNet50":
        pretrained_model = models.resnet50(pretrained=isTrained)
        pretrained_model.eval()
    elif network == "Custom":
        pretrained_model = loadModel(training, structure)

    if torch.cuda.is_available():
        pretrained_model = pretrained_model.cuda()


    return (original_image,
            prep_img,
            target_class,
            file_name_to_export,
            pretrained_model)


def prediction_reader(preds,length,choose_network):

    dict = {}
    if choose_network == 'Custom':
        classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')
        key = (0,1,2,3,4,5,6,7,8,9)
        for i in key:
            dict[i] = classes[i]
    else:
        with open("input_images/labels.txt") as f:
            for line in f:
               (key, val) = line.split(': ')
               val = val[1:-3]
               val = val.split(',')[0]
               dict[int(key)] = val

    output = F.softmax(torch.from_numpy(preds), dim=0).numpy()
    toppreds = output.argsort()[-length:][::-1]
    labels = [dict[x] for x in toppreds]
    return labels,output[toppreds]




