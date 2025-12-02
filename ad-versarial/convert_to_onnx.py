#!/usr/bin/env python3
"""
Convert page_based_yolov3 Keras model to ONNX format for RKNN conversion.
"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import tensorflow as tf
from tensorflow import keras
import tf2onnx
import numpy as np

# Fixed input size for RKNN
INPUT_SIZE = 416

print('Loading Keras model...')
model = keras.models.load_model('models/page_based_yolov3.h5', compile=False)
print('Model loaded successfully!')

# Create a new model with fixed input shape
input_layer = keras.layers.Input(shape=(INPUT_SIZE, INPUT_SIZE, 3), name='input_image')

# Get the functional model's output by calling it on the new input
outputs = model(input_layer)

# Create new model with fixed input
fixed_model = keras.Model(inputs=input_layer, outputs=outputs, name='yolov3_ad_detector')
print(f'Fixed input shape: {fixed_model.input_shape}')
print(f'Output shapes: {[o.shape for o in fixed_model.outputs]}')

# Convert to ONNX
print('\nConverting to ONNX...')
output_path = 'models/page_based_yolov3.onnx'

# Use tf2onnx to convert
spec = (tf.TensorSpec((1, INPUT_SIZE, INPUT_SIZE, 3), tf.float32, name="input_image"),)

model_proto, _ = tf2onnx.convert.from_keras(
    fixed_model,
    input_signature=spec,
    opset=13,
    output_path=output_path
)

print(f'\nONNX model saved to: {output_path}')
print(f'Model size: {os.path.getsize(output_path) / 1024 / 1024:.1f} MB')
