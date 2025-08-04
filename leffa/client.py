import socket
import struct
import json
import base64
import io
from PIL import Image


def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def base64_to_image(b64_string, save_path):
    img_bytes = base64.b64decode(b64_string)
    img = Image.open(io.BytesIO(img_bytes))
    img.save(save_path)
    print(f"Saved: {save_path}")

def send_request(server_ip='127.0.0.1', server_port=8899):
    # 构建图片路径和参数（请根据实际路径修改）
    data = {
        "control_type": "virtual_tryon",  # 或 "pose_transfer"
        "vt_src_image": image_to_base64("./ckpts/examples/person1/01350_00.jpg"),  # 替换成你的路径
        "vt_ref_image": image_to_base64("./ckpts/examples/garment/01449_00.jpg"),
        "params": {
            "ref_acceleration": False,
            "step": 30,
            "scale": 2.5,
            "seed": 42,
            "vt_model_type": "viton_hd",
            "vt_garment_type": "dresses",
            "vt_repaint": False,
            "preprocess_garment": False
        }
    }

    json_bytes = json.dumps(data).encode()
    json_length = struct.pack('!I', len(json_bytes))

    # 连接服务器
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.connect((server_ip, server_port))
        client_socket.sendall(json_length)
        client_socket.sendall(json_bytes)

        # 接收响应长度
        result_length_bytes = client_socket.recv(4)
        result_length = struct.unpack('!I', result_length_bytes)[0]

        # 接收响应数据
        result_data = b""
        while len(result_data) < result_length:
            packet = client_socket.recv(result_length - len(result_data))
            if not packet:
                break
            result_data += packet

        result = json.loads(result_data)

        if "error" in result:
            print(f" Error from server: {result['error']}")
        else:
            # 保存图像结果
            base64_to_image(result["gen_image"], "gen_image.png")
            base64_to_image(result["mask"], "mask.png")
            base64_to_image(result["densepose"], "densepose.png")

if __name__ == "__main__":
    send_request(server_ip="127.0.0.1", server_port=8899)  # 如果本机运行改为127.0.0.1
