import socket
import struct
import json
import numpy as np
from PIL import Image
import io
import base64
from app import LeffaPredictor, process_image_request
import os
import time

# 初始化预测器
leffa_predictor = LeffaPredictor()

def receive_image_and_data(conn):
    # 接收数据长度
    data_length_bytes = conn.recv(4)
    data_length = struct.unpack('!I', data_length_bytes)[0]

    # 接收 JSON 数据
    json_data = b""
    while len(json_data) < data_length:
        packet = conn.recv(data_length - len(json_data))
        if not packet:
            break
        json_data += packet
    data = json.loads(json_data)

    # 接收图片数据
    image_data = {}
    for key in ['vt_src_image', 'vt_ref_image', 'pt_src_image', 'pt_ref_image']:
        if key in data and data[key]:
            img_bytes = base64.b64decode(data[key])
            img = Image.open(io.BytesIO(img_bytes))
            temp_path = f'./{key}.png'
            img.save(temp_path)
            image_data[key] = temp_path

    return image_data, data['control_type'], data.get('params', {})

def send_result(conn, gen_image, mask, densepose):
    # 将 numpy 数组转换为 PIL 图像
    gen_image_pil = Image.fromarray(gen_image)
    mask_pil = Image.fromarray(mask)
    densepose_pil = Image.fromarray(densepose)

    # 将图像转换为 base64 编码
    buffers = []
    for img in [gen_image_pil, mask_pil, densepose_pil]:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffers.append(base64.b64encode(buffer.getvalue()).decode())

    result = {
        'gen_image': buffers[0],
        'mask': buffers[1],
        'densepose': buffers[2]
    }
    result_json = json.dumps(result).encode()
    conn.sendall(struct.pack('!I', len(result_json)))
    conn.sendall(result_json)

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('0.0.0.0', 8899))
    server_socket.listen(5)
    print("Server listening on port 8899")

    while True:
        conn, addr = server_socket.accept()
        print(f"Connected by {addr}")
        try:
            image_data, control_type, params = receive_image_and_data(conn)
            gen_image, mask, densepose = process_image_request(image_data, control_type, **params)
            send_result(conn, gen_image, mask, densepose)
            print("图像生成并发送成功。")
        except Exception as e:
            print(f"Error: {e}")
            error_msg = json.dumps({'error': str(e)}).encode()
            conn.sendall(struct.pack('!I', len(error_msg)))
            conn.sendall(error_msg)
        finally:
            conn.close()

if __name__ == "__main__":
    main()
