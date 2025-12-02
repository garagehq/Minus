#!/usr/bin/env python3
"""
Convert Percival Keras model (from Sq2.json) to ONNX for RKNN conversion.

The Sq2.json file is a Frugally Deep format containing:
- Keras model architecture (exported from Keras 2.2.2)
- Weights embedded in 'trainable_params'

Since Keras 3.x can't directly load Keras 2.2.2 JSON configs,
we manually reconstruct the model from the parsed architecture.
"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'  # Force CPU

import json
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
import tf2onnx

INPUT_SIZE = 224
JSON_MODEL = 'percival_model/Sq2.json'
ONNX_MODEL = 'models/percival_ad_detector.onnx'


def fire_module(x, squeeze_filters, expand_filters, name_prefix):
    """SqueezeNet Fire module: squeeze (1x1) + expand (1x1 & 3x3)"""
    # Squeeze
    squeeze = layers.Conv2D(squeeze_filters, (1, 1), padding='valid', name=f'{name_prefix}_squeeze')(x)
    squeeze = layers.Activation('relu', name=f'{name_prefix}_squeeze_act')(squeeze)

    # Expand 1x1
    expand1x1 = layers.Conv2D(expand_filters, (1, 1), padding='valid', name=f'{name_prefix}_expand1x1')(squeeze)
    expand1x1 = layers.Activation('relu', name=f'{name_prefix}_expand1x1_act')(expand1x1)

    # Expand 3x3
    expand3x3 = layers.Conv2D(expand_filters, (3, 3), padding='same', name=f'{name_prefix}_expand3x3')(squeeze)
    expand3x3 = layers.Activation('relu', name=f'{name_prefix}_expand3x3_act')(expand3x3)

    # Concatenate
    return layers.Concatenate(axis=-1, name=f'{name_prefix}_concat')([expand1x1, expand3x3])


def build_percival_model():
    """
    Build Percival's exact SqueezeNet architecture from Sq2.json.

    Architecture from JSON:
    - Input: 224x224x3
    - Conv2D(64, 3x3, stride=2) -> ReLU -> MaxPool(3x3, stride=2)
    - Fire3: sq=16, exp=64 -> Fire4: sq=16, exp=64 -> MaxPool
    - Fire6: sq=32, exp=128 -> Fire7: sq=32, exp=128 -> MaxPool
    - Fire9: sq=48, exp=256 -> Fire10: sq=64, exp=256
    - Dropout -> Conv(2) -> ReLU -> AvgPool(13x13) -> Flatten
    """
    inputs = layers.Input(shape=(INPUT_SIZE, INPUT_SIZE, 3), name='input_image')

    # Initial convolution (features.0)
    x = layers.Conv2D(64, (3, 3), strides=(2, 2), padding='valid', name='conv1')(inputs)
    x = layers.Activation('relu', name='relu1')(x)

    # MaxPool (features.2)
    x = layers.MaxPooling2D(pool_size=(3, 3), strides=(2, 2), name='pool2')(x)

    # Fire3: squeeze=16, expand=64 (output 128)
    x = fire_module(x, squeeze_filters=16, expand_filters=64, name_prefix='fire3')

    # Fire4: squeeze=16, expand=64 (output 128)
    x = fire_module(x, squeeze_filters=16, expand_filters=64, name_prefix='fire4')

    # MaxPool (features.5)
    x = layers.MaxPooling2D(pool_size=(3, 3), strides=(2, 2), name='pool5')(x)

    # Fire6: squeeze=32, expand=128 (output 256)
    x = fire_module(x, squeeze_filters=32, expand_filters=128, name_prefix='fire6')

    # Fire7: squeeze=32, expand=128 (output 256)
    x = fire_module(x, squeeze_filters=32, expand_filters=128, name_prefix='fire7')

    # MaxPool (features.8)
    x = layers.MaxPooling2D(pool_size=(3, 3), strides=(2, 2), name='pool8')(x)

    # Fire9: squeeze=48, expand=256 (output 512)
    x = fire_module(x, squeeze_filters=48, expand_filters=256, name_prefix='fire9')

    # Fire10: squeeze=64, expand=256 (output 512)
    x = fire_module(x, squeeze_filters=64, expand_filters=256, name_prefix='fire10')

    # Classifier
    x = layers.Dropout(0.5, name='dropout')(x)
    x = layers.Conv2D(2, (1, 1), padding='valid', name='conv_final')(x)
    x = layers.Activation('relu', name='relu_final')(x)
    x = layers.AveragePooling2D(pool_size=(13, 13), name='avgpool')(x)
    x = layers.Flatten(name='flatten')(x)

    # No softmax - model outputs logits based on JSON (no softmax layer)
    # Actually looking at usage, softmax is applied during inference
    outputs = layers.Activation('softmax', name='softmax')(x)

    return keras.Model(inputs, outputs, name='percival_ad_detector')


def decode_frugally_deep_weights(base64_str):
    """Decode Frugally Deep base64-encoded weights."""
    import base64
    import struct

    # Decode base64
    raw_bytes = base64.b64decode(base64_str)

    # Unpack as float32 (little-endian)
    num_floats = len(raw_bytes) // 4
    floats = struct.unpack(f'<{num_floats}f', raw_bytes)
    return np.array(floats, dtype=np.float32)


def load_weights_from_json(model, json_path):
    """Load weights from Frugally Deep JSON format."""
    print(f"Loading weights from {json_path}...")
    with open(json_path, 'r') as f:
        model_data = json.load(f)

    if 'trainable_params' not in model_data:
        print("No trainable_params found in JSON!")
        return False

    params = model_data['trainable_params']
    print(f"Found {len(params)} layer weight entries in JSON")

    # Build a mapping from original layer names to our layer names
    # Original names are like: features.3.squeeze0.xxx -> fire3_squeeze
    name_mapping = {
        'features.00': 'conv1',
        'features.3.squeeze': 'fire3_squeeze',
        'features.3.expand1x1': 'fire3_expand1x1',
        'features.3.expand3x3': 'fire3_expand3x3',
        'features.4.squeeze': 'fire4_squeeze',
        'features.4.expand1x1': 'fire4_expand1x1',
        'features.4.expand3x3': 'fire4_expand3x3',
        'features.6.squeeze': 'fire6_squeeze',
        'features.6.expand1x1': 'fire6_expand1x1',
        'features.6.expand3x3': 'fire6_expand3x3',
        'features.7.squeeze': 'fire7_squeeze',
        'features.7.expand1x1': 'fire7_expand1x1',
        'features.7.expand3x3': 'fire7_expand3x3',
        'features.9.squeeze': 'fire9_squeeze',
        'features.9.expand1x1': 'fire9_expand1x1',
        'features.9.expand3x3': 'fire9_expand3x3',
        'features.10.squeeze': 'fire10_squeeze',
        'features.10.expand1x1': 'fire10_expand1x1',
        'features.10.expand3x3': 'fire10_expand3x3',
        'classifier.1': 'conv_final',
    }

    # Create layer lookup
    layer_by_name = {l.name: l for l in model.layers}

    loaded_count = 0
    for json_key, layer_weights in params.items():
        # Find our layer name
        our_layer_name = None
        for prefix, name in name_mapping.items():
            if json_key.startswith(prefix):
                our_layer_name = name
                break

        if our_layer_name is None:
            print(f"  Skipping unknown layer: {json_key}")
            continue

        if our_layer_name not in layer_by_name:
            print(f"  Layer {our_layer_name} not found in model")
            continue

        layer = layer_by_name[our_layer_name]
        current_weights = layer.get_weights()

        if len(current_weights) == 0:
            continue

        try:
            # Decode weights and bias from base64
            new_weights = []

            # Weights (kernels) - concatenate all chunks
            if 'weights' in layer_weights:
                all_weight_data = []
                for w_str in layer_weights['weights']:
                    w_data = decode_frugally_deep_weights(w_str)
                    all_weight_data.extend(w_data)

                # Reshape to match expected shape
                expected_shape = current_weights[0].shape
                total_expected = np.prod(expected_shape)

                if len(all_weight_data) == total_expected:
                    # Frugally Deep stores in (out_channels, in_channels, H, W) order
                    # Keras expects (H, W, in_channels, out_channels)
                    w_array = np.array(all_weight_data, dtype=np.float32)

                    # Determine if this is a conv layer and needs transpose
                    if len(expected_shape) == 4:
                        # Try OIHW -> HWIO transpose
                        out_ch = expected_shape[3]
                        in_ch = expected_shape[2]
                        h = expected_shape[0]
                        w = expected_shape[1]
                        try:
                            w_oihw = w_array.reshape(out_ch, in_ch, h, w)
                            w_hwio = np.transpose(w_oihw, (2, 3, 1, 0))
                            new_weights.append(w_hwio)
                        except:
                            # Fall back to direct reshape
                            new_weights.append(w_array.reshape(expected_shape))
                    else:
                        new_weights.append(w_array.reshape(expected_shape))
                else:
                    print(f"  Weight size mismatch for {our_layer_name}: {len(all_weight_data)} vs {total_expected}")

            # Bias - concatenate all chunks
            if 'bias' in layer_weights and len(current_weights) > 1:
                all_bias_data = []
                for b_str in layer_weights['bias']:
                    b_data = decode_frugally_deep_weights(b_str)
                    all_bias_data.extend(b_data)
                new_weights.append(np.array(all_bias_data, dtype=np.float32))

            if len(new_weights) == len(current_weights):
                layer.set_weights(new_weights)
                loaded_count += 1
                print(f"  Loaded weights for {our_layer_name}")
            else:
                print(f"  Weight count mismatch for {our_layer_name}: {len(new_weights)} vs {len(current_weights)}")

        except Exception as e:
            print(f"  Error loading weights for {our_layer_name}: {e}")

    print(f"Successfully loaded weights for {loaded_count} layers")
    return loaded_count > 0


def main():
    print("Building Percival SqueezeNet model...")
    model = build_percival_model()
    model.summary()

    print(f"\nInput shape: {model.input_shape}")
    print(f"Output shape: {model.output_shape}")

    # Try to load weights from JSON
    # Note: This may not work perfectly due to architecture differences
    # The model will still work but with random weights
    try:
        load_weights_from_json(model, JSON_MODEL)
    except Exception as e:
        print(f"Could not load weights: {e}")
        print("Proceeding with randomly initialized weights for architecture validation...")

    # Test inference
    print("\nTesting inference...")
    test_input = np.random.rand(1, INPUT_SIZE, INPUT_SIZE, 3).astype(np.float32) * 255
    output = model.predict(test_input, verbose=0)
    print(f"Test output shape: {output.shape}")
    print(f"Test output (ad probability): {output}")

    # Convert to ONNX
    print(f"\nConverting to ONNX...")
    spec = (tf.TensorSpec((1, INPUT_SIZE, INPUT_SIZE, 3), tf.float32, name="input_image"),)

    model_proto, _ = tf2onnx.convert.from_keras(
        model,
        input_signature=spec,
        opset=13,
        output_path=ONNX_MODEL
    )

    print(f"\nONNX model saved to: {ONNX_MODEL}")
    print(f"Model size: {os.path.getsize(ONNX_MODEL) / 1024 / 1024:.2f} MB")

if __name__ == '__main__':
    main()
