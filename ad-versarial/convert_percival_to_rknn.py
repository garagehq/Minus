#!/usr/bin/env python3
"""
Convert Percival ONNX model to RKNN format for RK3588 NPU.
"""
from rknn.api import RKNN

INPUT_SIZE = 224
ONNX_MODEL = 'models/percival_ad_detector.onnx'
RKNN_MODEL = 'models/percival_ad_detector_rk3588.rknn'

def main():
    rknn = RKNN(verbose=True)

    # Configure for RK3588
    # Percival expects 0-255 RGB input (no normalization in original model)
    print('--> Configuring model')
    rknn.config(
        target_platform='rk3588'
        # No mean/std - model expects 0-255 RGB input
    )
    print('done')

    # Load ONNX model
    print('--> Loading ONNX model')
    ret = rknn.load_onnx(model=ONNX_MODEL)
    if ret != 0:
        print('Load ONNX model failed!')
        return ret
    print('done')

    # Build RKNN model (FP16, no quantization)
    print('--> Building RKNN model')
    ret = rknn.build(do_quantization=False)
    if ret != 0:
        print('Build RKNN model failed!')
        return ret
    print('done')

    # Export RKNN model
    print('--> Exporting RKNN model')
    ret = rknn.export_rknn(RKNN_MODEL)
    if ret != 0:
        print('Export RKNN model failed!')
        return ret
    print(f'done - saved to {RKNN_MODEL}')

    rknn.release()
    return 0

if __name__ == '__main__':
    main()
