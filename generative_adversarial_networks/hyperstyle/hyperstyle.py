import os
import sys
import time
import argparse

import numpy as np
import cv2

import ailia

# parameters
from utils_ import AILIA_MODELS_BASE_DIR, CHECKPOINTS, AVERAGE, CHOICES, IMAGE_HEIGHT, IMAGE_WIDTH, RESIZE_HEIGHT, RESIZE_WIDTH, IMAGE_PATH, SAVE_IMAGE_PATH, ALIGNED_PATH

# import original modules
sys.path.append(os.path.join(AILIA_MODELS_BASE_DIR, 'util'))
sys.path.append(os.path.join(AILIA_MODELS_BASE_DIR, 'style_transfer')) # import setup for face alignement (psgan)
sys.path.append(os.path.join(AILIA_MODELS_BASE_DIR, 'style_transfer/psgan')) # import preprocess for face alignement (psgan)
from utils import get_base_parser, update_parser, get_savepath  # noqa: E402
from model_utils import check_and_download_models  # noqa: E402
from image_utils import load_image  # noqa: E402
import webcamera_utils  # noqa: E402
from align_crop import align_face # noqa: E402
from utils_ import np2im

# logger
from logging import getLogger   # noqa: E402
logger = getLogger(__name__)

# ======================
# MODELS
# ======================

WEIGHT_PATH = os.path.join(CHECKPOINTS, 'hyperstyle.onnx')
MODEL_PATH = os.path.join(CHECKPOINTS, 'hyperstyle.onnx.prototxt')

HYPERNET_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'hypernet.onnx')
HYPERNET_MODEL_PATH = os.path.join(CHECKPOINTS, 'hypernet.onnx.prototxt')

HYPERSTYLE_DECODER_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'hyperstyle_decoder.onnx')
HYPERSTYLE_DECODER_MODEL_PATH = os.path.join(CHECKPOINTS, 'hyperstyle_decoder.onnx.prototxt')

DECODER_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'decoder.onnx')
DECODER_MODEL_PATH = os.path.join(CHECKPOINTS, 'decoder.onnx.prototxt')

RESTYLE_E4E_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'restyle_e4e.onnx')
RESTYLE_E4E_MODEL_PATH = os.path.join(CHECKPOINTS, 'restyle_e4e.onnx.prototxt')

W_ENCODER_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'w_encoder.onnx')
W_ENCODER_MODEL_PATH = os.path.join(CHECKPOINTS, 'w_encoder.onnx.prototxt')

FACE_POOL_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'hyperstyle_face_pool.onnx')
FACE_POOL_MODEL_PATH = os.path.join(CHECKPOINTS, 'hyperstyle_face_pool.onnx.prototxt')

E4E_FACE_POOL_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'e4e_face_pool.onnx')
E4E_FACE_POOL_MODEL_PATH = os.path.join(CHECKPOINTS, 'e4e_face_pool.onnx.prototxt')

DECODER_FACE_POOL_WEIGHT_PATH = os.path.join(CHECKPOINTS, 'decoder_face_pool.onnx')
DECODER_FACE_POOL_MODEL_PATH = os.path.join(CHECKPOINTS, 'decoder_face_pool.onnx.prototxt')

FACE_ALIGNMENT_WEIGHT_PATH = os.path.join(AILIA_MODELS_BASE_DIR, "face_recognition/face_alignment/2DFAN-4.onnx")
FACE_ALIGNMENT_MODEL_PATH = os.path.join(AILIA_MODELS_BASE_DIR, "face_recognition/face_alignment/2DFAN-4.onnx.prototxt")

FACE_DETECTOR_WEIGHT_PATH = os.path.join(AILIA_MODELS_BASE_DIR, "face_detection/blazeface/blazeface.onnx")
FACE_DETECTOR_MODEL_PATH = os.path.join(AILIA_MODELS_BASE_DIR, "face_detection/blazeface/blazeface.onnx.prototxt")

REMOTE_PATH = 'https://storage.googleapis.com/ailia-models/hyperstyle/'
FACE_ALIGNMENT_REMOTE_PATH = "https://storage.googleapis.com/ailia-models/face_alignment/"
FACE_DETECTOR_REMOTE_PATH = "https://storage.googleapis.com/ailia-models/blazeface/"

face_alignment_path = [FACE_ALIGNMENT_MODEL_PATH, FACE_ALIGNMENT_WEIGHT_PATH]
face_detector_path = [FACE_DETECTOR_MODEL_PATH, FACE_DETECTOR_WEIGHT_PATH]


# ======================
# Arguemnt Parser Config
# ======================
parser = get_base_parser(
    "Hyperstyle", IMAGE_PATH, SAVE_IMAGE_PATH,
)
parser.add_argument(
    "--inversion",
    action="store_true",
    help="Run the inversion task",
)
parser.add_argument(
    "--adaptation",
    action="store_true",
    help="Run the adaptation task",
)
parser.add_argument(
    "-m", "--model", 
    type=str, default="cartoon", 
    help="Choose the domain you want (for domain adaptation task)", 
    choices=CHOICES
)
parser.add_argument(
    "-iter", "--iteration",
    default=2, type=int,
    help="Number of iterations per batch (default 2)"
)
parser.add_argument(
    "-d", "--debug",
    action="store_true",
    help="Debugger"
)
parser.add_argument(
    "--side_by_side",
    action="store_true",
    help="Save the input and output images side-by-side",
)
parser.add_argument(
    "--use_dlib",
    action="store_true",
    help="Use dlib models for face alignment",
)
parser.add_argument(
    "--onnx",
    action="store_true",
    help="Use onnxruntime for inference",
)
parser.add_argument(
    "--config_file",
    default=os.path.join(AILIA_MODELS_BASE_DIR, "style_transfer/psgan/configs/base.yaml"),
    metavar="FILE",
    help="Path to config file for psgan",
)
parser.add_argument(
    "opts",
    help="Modify config options using the command-line (for psgan)",
    default=None,
    nargs=argparse.REMAINDER,
)
args = update_parser(parser)


# ======================
# Utils
# ======================
def check(path):
    import onnx
    onnx_model = onnx.load(path)
    onnx.checker.check_model(onnx_model)

def run_on_batch(inputs, net, face_pool_net, iters, avg_image_for_batch):
    y_hat, latent = None, np.load(os.path.join(AVERAGE, 'e4e_latent_avg.npy'))
    for iter in range(iters):
        if iter == 0:
            x_input = np.concatenate([inputs, avg_image_for_batch], axis=1)
        else:
            x_input = np.concatenate([inputs, y_hat], axis=1)

        # ReStyle e4e
        y_hat, latent = net.predict({'x_input': x_input, 'latent_in': latent})

        # resize input to 256 before feeding into next iteration
        y_hat = face_pool_net.predict(y_hat)

    return y_hat, latent

def get_initial_inversion(x, encoder, decoder, face_pool_decoder):
    codes = encoder.predict(x)
    latent_avg = np.load(os.path.join(AVERAGE, 'hyperstyle_latent_avg.npy'))

    if codes.ndim == 2:
        codes = codes + np.tile(latent_avg, (codes.shape[0], 1, 1, 1))[:, 0, :]
    else:
        codes = codes + np.tile(latent_avg, (codes.shape[0], 1, 1, 1))
    codes = codes[0]
    
    y_hat = decoder.predict([codes])[0]

    y_hat = face_pool_decoder.predict(y_hat)
    return y_hat, codes


def run_inversion(inputs, nets, iters):
    latent, weights_deltas = None, None

    # Encoder, Decoder
    y_hat, codes = get_initial_inversion(inputs, nets[7], nets[3], nets[4])

    for iter in range(iters):
        # Hyperstyle
        x_input = np.concatenate([inputs, y_hat], axis=1)
        """
        ort_session = onnxruntime.InferenceSession("checkpoints/hypernet.onnx")
        ort_inputs = {ort_session.get_inputs()[0].name: x_input.astype(np.single)}
        hypernet_outputs = ort_session.run(None, ort_inputs)
        print(len(hypernet_outputs))
        print(hypernet_outputs[0].shape)
        print(hypernet_outputs[1].shape)
        """
        # Hyperstyle - Hypernet
        hypernet_outputs = nets[0].run(x_input)

        if weights_deltas is None:
            weights_deltas = hypernet_outputs
        else:
            weights_deltas = [weights_deltas[i] + hypernet_outputs[i] if ((weights_deltas[i] is not None) and (hypernet_outputs[i] is not None)) else None
                                  for i in range(len(hypernet_outputs))]
        
        """
        #y_hat, latent = nets[1].predict({'[codes]': [codes], 'weights_deltas': weights_deltas})
        ort_session = onnxruntime.InferenceSession("checkpoints/hyperstyle_decoder.onnx")
        ort_inputs = {ort_session.get_inputs()[i+1].name: weights_deltas[i].astype(np.single) for i in range(len(weights_deltas))}
        ort_inputs[ort_session.get_inputs()[0].name] = codes.astype(np.single)
        y_hat, latent = ort_session.run(None, ort_inputs)
        print(y_hat.shape, latent.shape)
        """
        
        params = {str(i): weights_deltas[i-1] for i in range(2, 27)}
        params['[codes]'] = codes
        params['weights_deltas'] = weights_deltas[0]
        # Hyperstyle - Decoder
        y_hat, latent = nets[1].run(params)

        # resize input to 256 before feeding into next iteration
        no_resize = y_hat
        y_hat = nets[2].predict(y_hat)

    return y_hat, latent, weights_deltas, codes, no_resize

# From original model
def filter_non_ffhq_layers_in_toonify_model(weights_deltas):
    toonify_ffhq_layer_idx = [14, 15, 17, 18, 20, 21, 23, 24]
    for i in range(len(weights_deltas)):
        if weights_deltas[i] is not None and i not in toonify_ffhq_layer_idx:
            weights_deltas[i] = np.zeros(weights_deltas[i].shape)
    return weights_deltas

def run_domain_adaptation(inputs, nets, iters, avg_image, weights_deltas=None):
    _, latents = run_on_batch(inputs, nets[5], nets[6], iters, avg_image)
    if weights_deltas is None:
        _, _, weights_deltas, _, _ = run_inversion(inputs, nets, iters)
    weights_deltas = filter_non_ffhq_layers_in_toonify_model(weights_deltas)

    """
    ort_session = onnxruntime.InferenceSession("checkpoints/fine_tuned_generator.onnx")
    ort_inputs = {ort_session.get_inputs()[i+1].name: weights_deltas[i].astype(np.single) for i in range(len(weights_deltas))}
    ort_inputs[ort_session.get_inputs()[0].name] = latents.astype(np.single)
    result_batch, _ = ort_session.run(None, ort_inputs)
    print(result_batch.shape)
    """

    params = {str(i): weights_deltas[i-1] for i in range(2, 27)}
    params['[latents]'] = latents
    params['weights_deltas'] = weights_deltas[0]
    # Fine-tuned generator
    result_batch, _ = nets[8].run(params)

    return result_batch

def inference(inputs, nets, iters):
    latent, result_batch, weights_deltas = None, None, None
    # Inversion task
    if args.inversion:
        _, result_latent, weights_deltas, _, no_resize = run_inversion(inputs, nets, iters)
        latent = (no_resize, result_latent)
    # Domain adaptation task
    if args.adaptation:
        e4e_avg_img = np.load(os.path.join(AVERAGE, 'e4e_image_avg.npy'))
        result_batch = run_domain_adaptation(inputs, nets, iters, e4e_avg_img, weights_deltas)
    return result_batch, latent

def post_processing(result_batch, input_img):
    for i in range(input_img.shape[0]):
        curr_result = np2im(result_batch[i])
        if args.side_by_side:
            input_im = np2im(input_img[i], input=True)
            res = np.concatenate([input_im, curr_result], axis=1)
        else:
            res = curr_result
    
    return res

def save_results(result_adaptation, result_inversion, input_img, filename):
    # post processing
    if args.adaptation:
        res = post_processing(result_adaptation, input_img)
        savepath = get_savepath(args.savepath, filename)
        # save image from domain adaptation
        logger.info(f'saved at : {savepath}')
        cv2.imwrite(savepath, res)

    if args.inversion:
        latent_img = post_processing(result_inversion[0], input_img)
        basename = os.path.splitext(os.path.basename(args.savepath))
        # save latent image from inversion
        savepath = os.path.join(os.path.dirname(args.savepath), f"{basename[0]}-latent{basename[1]}")
        logger.info(f'saved at : {savepath}')
        cv2.imwrite(savepath, latent_img)
        # save latent numpy file
        for i in range(input_img.shape[0]):
            savepath = os.path.join(os.path.dirname(args.savepath), f"{basename[0]}-latent.npy")
            logger.info(f'saved at : {savepath}')
            np.save(savepath, result_inversion[1][i])

# ======================
# Main functions
# ======================
def recognize_from_image(filename, nets): 
    # face alignment
    aligned = align_face(filename, args, face_alignment_path, face_detector_path)
    if aligned is not None:
        path = os.path.join(ALIGNED_PATH, filename.split('/')[-1])
        aligned.save(path)
    else: 
        path = filename

    input_img = load_image(
        path,
        (IMAGE_HEIGHT, IMAGE_WIDTH),
        normalize_type='255',
        gen_input_ailia=True,
    )

    input_img_resized = load_image(
        path,
        (RESIZE_HEIGHT, RESIZE_WIDTH),
        normalize_type='255',
        gen_input_ailia=True,
    )
    input_img_resized = (input_img_resized * 2) - 1
    
    # inference
    logger.info('Start inference...')
    if args.benchmark:
        logger.info('BENCHMARK mode')
        for i in range(5):
            # ailia prediction
            start = int(round(time.time() * 1000))
            result_adaptation, result_inversion = inference(input_img_resized, nets, args.iteration)
            end = int(round(time.time() * 1000))
            logger.info(f'\tailia processing time {end - start} ms')
    else:
        # ailia prediction
        result_adaptation, result_inversion = inference(input_img_resized, nets, args.iteration)
    
    save_results(result_adaptation, result_inversion, input_img, filename)


def recognize_from_video(filename, nets):

    capture = webcamera_utils.get_capture(args.video)

    # create video writer if savepath is specified as video format
    if args.savepath != SAVE_IMAGE_PATH:
        writer = webcamera_utils.get_writer(
            args.savepath, IMAGE_HEIGHT, IMAGE_WIDTH
        )
    else:
        writer = None

    while(True):
        ret, frame = capture.read()
        if (cv2.waitKey(1) & 0xFF == ord('q')) or not ret:
            break

        # Resize by padding the perimeter.
        _, input_data = webcamera_utils.preprocess_frame(
            frame, IMAGE_HEIGHT, IMAGE_WIDTH, normalize_type='255'
        )

        resized_input = cv2.resize(input_data[0].transpose(1,2,0), (RESIZE_HEIGHT, RESIZE_WIDTH))
        resized_input = np.expand_dims(resized_input.transpose(2,0,1), axis=0)
        resized_input = (resized_input * 2) - 1

        # inference
        result_adaptation, result_inversion = inference(resized_input, nets, args.iteration)
            
        # post-processing
        if args.inversion:
            res_img = post_processing(result_inversion[0], input_data)
            cv2.imshow('frame', res_img)
            # save results
            if writer is not None:
                writer.write(res_img)
                basename = os.path.splitext(os.path.basename(args.savepath))
                savepath = os.path.join(os.path.dirname(args.savepath), f"{basename[0]}-latent.npy")
                np.save(savepath, result_inversion[1][0])

        if args.adaptation:
            res_img = post_processing(result_adaptation, input_data)
            cv2.imshow('frame', res_img)
            # save results
            if writer is not None:
                writer.write(res_img)

    capture.release()
    cv2.destroyAllWindows()
    if writer is not None:
        writer.release()


def main():
    # model files check and download
    models = [HYPERNET_MODEL_PATH, HYPERSTYLE_DECODER_MODEL_PATH, FACE_POOL_MODEL_PATH, DECODER_MODEL_PATH, DECODER_FACE_POOL_MODEL_PATH, RESTYLE_E4E_MODEL_PATH, E4E_FACE_POOL_MODEL_PATH, W_ENCODER_MODEL_PATH, FINE_TUNED_MODEL_PATH]
    weights = [HYPERNET_WEIGHT_PATH, HYPERSTYLE_DECODER_WEIGHT_PATH, FACE_POOL_WEIGHT_PATH, DECODER_WEIGHT_PATH, DECODER_FACE_POOL_WEIGHT_PATH, RESTYLE_E4E_WEIGHT_PATH, E4E_FACE_POOL_WEIGHT_PATH, W_ENCODER_WEIGHT_PATH, FINE_TUNED_WEIGHT_PATH]
    """
    for model, weight in zip(models, weights):
        check_and_download_models(weight, model, REMOTE_PATH)
    """
    if not args.use_dlib:
        check_and_download_models(
            FACE_ALIGNMENT_WEIGHT_PATH,
            FACE_ALIGNMENT_MODEL_PATH,
            FACE_ALIGNMENT_REMOTE_PATH
        )
        check_and_download_models(
            FACE_DETECTOR_WEIGHT_PATH,
            FACE_DETECTOR_MODEL_PATH,
            FACE_DETECTOR_REMOTE_PATH
        )

    # debug
    if args.debug:
        for weight in weights:
            check(weight)
        if args.use_dlib:
            check(FACE_ALIGNMENT_WEIGHT_PATH)
            check(FACE_DETECTOR_WEIGHT_PATH)
        logger.info('Debug OK.')
    else:
        # net initialize
        nets = [ailia.Net(model, weight, env_id=args.env_id) for model, weight in zip(models, weights)]
        # video mode
        if args.video is not None:
            recognize_from_video(SAVE_IMAGE_PATH, nets)
        # image mode
        else:
            # input image loop
            for image_path in args.input:
                recognize_from_image(image_path, nets)
    logger.info('Script finished successfully.')


if __name__ == '__main__':
    if args.model in CHOICES:
        FINE_TUNED_WEIGHT_PATH = os.path.join(CHECKPOINTS, f'{args.model}.onnx')
        FINE_TUNED_MODEL_PATH = os.path.join(CHECKPOINTS, f'{args.model}.onnx.prototxt')
    else:
        logger.info(f'{args.model}: unrecognized --model argument.')
        exit(-1)
    main()