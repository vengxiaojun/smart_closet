import numpy as np
from PIL import Image
#from huggingface_hub import snapshot_download
from leffa.transform import LeffaTransform
from leffa.model import LeffaModel
from leffa.inference import LeffaInference
from leffa_utils.garment_agnostic_mask_predictor import AutoMasker
from leffa_utils.densepose_predictor import DensePosePredictor
from leffa_utils.utils import resize_and_center, get_agnostic_mask_hd, get_agnostic_mask_dc, preprocess_garment_image
from preprocess.humanparsing.run_parsing import Parsing
from preprocess.openpose.run_openpose import OpenPose
import os
import time

# 下载权重
#snapshot_download(repo_id="franciszzj/Leffa", local_dir="./ckpts")

if not os.path.exists("./ckpts") or not os.path.isdir("./ckpts"):
    raise FileNotFoundError("ckpts 模型文件夹未找到，请先手动下载或上传所需模型。")
    
class LeffaPredictor(object):
    def __init__(self):
        self.mask_predictor = AutoMasker(
            densepose_path="./ckpts/densepose",
            schp_path="./ckpts/schp",
        )
        self.densepose_predictor = DensePosePredictor(
            config_path="./ckpts/densepose/densepose_rcnn_R_50_FPN_s1x.yaml",
            weights_path="./ckpts/densepose/model_final_162be9.pkl",
        )
        self.parsing = Parsing(
            atr_path="./ckpts/humanparsing/parsing_atr.onnx",
            lip_path="./ckpts/humanparsing/parsing_lip.onnx",
        )
        self.openpose = OpenPose(
            body_model_path="./ckpts/openpose/body_pose_model.pth",
        )

        # 懒加载模型
        self.vt_inference_hd = None
        self.vt_inference_dc = None
        self.pt_inference = None

    def get_inference_model(self, control_type, vt_model_type=None):
        if control_type == "virtual_tryon":
            if vt_model_type == "viton_hd":
                if self.vt_inference_hd is None:
                    vt_model_hd = LeffaModel(
                        pretrained_model_name_or_path="./ckpts/stable-diffusion-inpainting",
                        pretrained_model="./ckpts/virtual_tryon.pth",
                        dtype="float16",
                    )
                    self.vt_inference_hd = LeffaInference(model=vt_model_hd)
                return self.vt_inference_hd

            elif vt_model_type == "dress_code":
                if self.vt_inference_dc is None:
                    vt_model_dc = LeffaModel(
                        pretrained_model_name_or_path="./ckpts/stable-diffusion-inpainting",
                        pretrained_model="./ckpts/virtual_tryon_dc.pth",
                        dtype="float16",
                    )
                    self.vt_inference_dc = LeffaInference(model=vt_model_dc)
                return self.vt_inference_dc

        elif control_type == "pose_transfer":
            if self.pt_inference is None:
                pt_model = LeffaModel(
                    pretrained_model_name_or_path="./ckpts/stable-diffusion-xl-1.0-inpainting-0.1",
                    pretrained_model="./ckpts/pose_transfer.pth",
                    dtype="float16",
                )
                self.pt_inference = LeffaInference(model=pt_model)
            return self.pt_inference

        raise ValueError(f"Unknown model type: {control_type} / {vt_model_type}")

    def leffa_predict(
        self,
        src_image_path,
        ref_image_path,
        control_type,
        ref_acceleration=False,
        step=50,
        scale=2.5,
        seed=42,
        vt_model_type="viton_hd",
        vt_garment_type="dresses",
        vt_repaint=False,
        preprocess_garment=False
    ):
        src_image = Image.open(src_image_path)
        src_image = resize_and_center(src_image, 768, 1024)

        if control_type == "virtual_tryon" and preprocess_garment:
            if ref_image_path.lower().endswith('.png'):
                ref_image = preprocess_garment_image(ref_image_path)
            else:
                raise ValueError("Only PNG images are supported for preprocessing")
        else:
            ref_image = Image.open(ref_image_path)
        ref_image = resize_and_center(ref_image, 768, 1024)

        src_image_array = np.array(src_image)

        if control_type == "virtual_tryon":
            src_image = src_image.convert("RGB")

            start = time.time()
            model_parse, _ = self.parsing(src_image.resize((384, 512)))
            print("🔍 Human Parsing Time:", time.time() - start, "seconds")

            start = time.time()
            keypoints = self.openpose(src_image.resize((384, 512)))
            print("🧍 OpenPose Keypoint Time:", time.time() - start, "seconds")

            if vt_model_type == "viton_hd":
                mask = get_agnostic_mask_hd(model_parse, keypoints, vt_garment_type)
            else:
                mask = get_agnostic_mask_dc(model_parse, keypoints, vt_garment_type)
            mask = mask.resize((768, 1024))
        else:
            mask = Image.fromarray(np.ones_like(src_image_array) * 255)

        if control_type == "virtual_tryon":
            if vt_model_type == "viton_hd":
                densepose = Image.fromarray(self.densepose_predictor.predict_seg(src_image_array)[:, :, ::-1])
            else:
                iuv = self.densepose_predictor.predict_iuv(src_image_array)
                seg = iuv[:, :, 0:1]
                seg = np.concatenate([seg] * 3, axis=-1)
                densepose = Image.fromarray(seg)
        else:
            iuv = self.densepose_predictor.predict_iuv(src_image_array)[:, :, ::-1]
            densepose = Image.fromarray(iuv)

        transform = LeffaTransform()
        data = transform({
            "src_image": [src_image],
            "ref_image": [ref_image],
            "mask": [mask],
            "densepose": [densepose],
        })

        inference = self.get_inference_model(control_type, vt_model_type)
        output = inference(
            data,
            ref_acceleration=ref_acceleration,
            num_inference_steps=step,
            guidance_scale=scale,
            seed=seed,
            repaint=vt_repaint,
        )
        gen_image = output["generated_image"][0]
        return np.array(gen_image), np.array(mask), np.array(densepose)

    def leffa_predict_vt(self, src_image_path, ref_image_path, ref_acceleration, step, scale, seed, vt_model_type, vt_garment_type, vt_repaint, preprocess_garment):
        return self.leffa_predict(
            src_image_path,
            ref_image_path,
            "virtual_tryon",
            ref_acceleration,
            step,
            scale,
            seed,
            vt_model_type,
            vt_garment_type,
            vt_repaint,
            preprocess_garment
        )

    def leffa_predict_pt(self, src_image_path, ref_image_path, ref_acceleration, step, scale, seed):
        return self.leffa_predict(
            src_image_path,
            ref_image_path,
            "pose_transfer",
            ref_acceleration,
            step,
            scale,
            seed
        )

# socket 使用会调用这个
leffa_predictor = LeffaPredictor()

def process_image_request(image_data, control_type, **kwargs):
    if control_type == "virtual_tryon":
        return leffa_predictor.leffa_predict_vt(
            image_data['vt_src_image'], image_data['vt_ref_image'], **kwargs
        )
    elif control_type == "pose_transfer":
        return leffa_predictor.leffa_predict_pt(
            image_data['pt_src_image'], image_data['pt_ref_image'], **kwargs
        )
    else:
        raise ValueError(f"Unknown control_type: {control_type}")
