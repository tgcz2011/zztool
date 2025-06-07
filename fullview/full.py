#!/usr/bin/env python3
"""
全景图像索引生成工具（增强版）
自动扫描目录、生成预览图、创建索引文件

修改版：使用Filebase兼容的CID计算方法
"""

import os
import json
import argparse
import io
import hashlib
import base58
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import datetime
import shutil

# 配置参数
THUMBNAIL_SIZE = (320, 180)  # 预览图尺寸
THUMBNAIL_DIR = "thumbnails"  # 预览图子目录
IPFS_GATEWAY = "https://collective-black-hippopotamus.myfilebase.com/ipfs/"


# CID计算相关函数
def encode_varint(num):
    """编码变长整数（Variable Integer）"""
    buf = io.BytesIO()
    while num >= 0x80:
        buf.write(bytes([(num & 0x7f) | 0x80]))
        num >>= 7
    buf.write(bytes([num & 0x7f]))
    return buf.getvalue()


def protobuf_encode_field(field_num, field_type, value):
    """Protocol Buffers字段编码"""
    # 计算字段标识符
    key = (field_num << 3) | field_type
    # 编码字段标识符
    result = encode_varint(key)

    # 根据字段类型编码值
    if field_type == 0:  # varint
        result += encode_varint(value)
    elif field_type == 2:  # length-delimited (string, bytes, embedded messages)
        result += encode_varint(len(value))
        result += value

    return result


def create_unixfs_format(data, file_type=2):
    """创建UnixFS格式的数据"""
    # UnixFS Data结构
    # Type字段 (1): 文件类型，2表示File
    type_field = protobuf_encode_field(1, 0, file_type)

    # Data字段 (2): 文件内容
    data_field = protobuf_encode_field(2, 2, data)

    # FileSize字段 (3): 文件大小
    filesize_field = protobuf_encode_field(3, 0, len(data))

    return type_field + data_field + filesize_field


def create_dag_pb_format(unixfs_data):
    """创建DAG-PB格式的数据"""
    # DAG-PB结构
    # Data字段 (1): UnixFS数据
    data_field = protobuf_encode_field(1, 2, unixfs_data)

    # Links字段 (2): 空，因为这是一个叶子节点

    return data_field


def calculate_cid(file_path):
    """
    计算Filebase兼容的IPFS CID (v0)

    使用DAG-PB格式和UnixFS格式包装数据，然后计算SHA-256哈希，
    最后添加多哈希前缀并使用Base58btc编码。

    Args:
        file_path: 文件路径

    Returns:
        str: CIDv0
    """
    # 读取文件内容
    with open(file_path, 'rb') as f:
        file_content = f.read()

    # 创建UnixFS格式的数据
    unixfs_data = create_unixfs_format(file_content)

    # 创建DAG-PB格式的数据
    dag_pb_data = create_dag_pb_format(unixfs_data)

    # 计算SHA-256哈希
    sha256_hash = hashlib.sha256(dag_pb_data).digest()

    # 添加多哈希前缀
    # 0x12 表示 sha2-256，0x20 表示长度为32字节
    multihash = bytes([0x12, 0x20]) + sha256_hash

    # 使用Base58btc编码
    return base58.b58encode(multihash).decode('utf-8')


def get_exif_data(image):
    """获取图像的EXIF数据"""
    exif_data = {}
    try:
        info = image._getexif()
        if info:
            for tag, value in info.items():
                decoded = TAGS.get(tag, tag)
                if decoded == "GPSInfo":
                    gps_data = {}
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                    exif_data[decoded] = gps_data
                else:
                    exif_data[decoded] = value
    except Exception as e:
        print(f"读取EXIF数据时出错: {e}")
    return exif_data


def convert_to_degrees(value):
    """将GPS坐标转换为十进制度数"""
    if isinstance(value, tuple):
        d, m, s = value
        return d + (m / 60.0) + (s / 3600.0)
    return value


def get_gps_location(exif_data):
    """从EXIF数据中提取GPS位置"""
    if "GPSInfo" not in exif_data:
        return None

    gps_info = exif_data["GPSInfo"]
    try:
        gps_latitude = gps_info.get("GPSLatitude")
        gps_latitude_ref = gps_info.get("GPSLatitudeRef")
        gps_longitude = gps_info.get("GPSLongitude")
        gps_longitude_ref = gps_info.get("GPSLongitudeRef")

        if not gps_latitude or not gps_longitude:
            return None

        lat = convert_to_degrees(gps_latitude)
        if gps_latitude_ref and gps_latitude_ref != "N":
            lat = -lat

        lon = convert_to_degrees(gps_longitude)
        if gps_longitude_ref and gps_longitude_ref != "E":
            lon = -lon

        return (lat, lon)
    except Exception as e:
        print(f"解析GPS位置时出错: {e}")
        return None


def create_thumbnail(image_path, output_dir):
    """创建预览图并保存到指定目录"""
    try:
        with Image.open(image_path) as img:
            # 保持宽高比生成预览图
            img.thumbnail(THUMBNAIL_SIZE)

            # 创建输出目录
            os.makedirs(output_dir, exist_ok=True)

            # 生成输出路径
            filename = os.path.basename(image_path)
            output_path = os.path.join(output_dir, filename)

            # 保存预览图
            img.save(output_path, "JPEG")

            return output_path
    except Exception as e:
        print(f"创建预览图失败: {e}")
        return None


def get_image_info(image_path, base_dir):
    """获取图像信息，包括尺寸、日期、GPS位置和IPFS链接"""
    try:
        # 计算CID并构建IPFS链接
        cid = calculate_cid(image_path)
        ipfs_url = f"{IPFS_GATEWAY}{cid}"

        with Image.open(image_path) as img:
            # 获取图像尺寸
            width, height = img.size

            # 获取EXIF数据
            exif_data = get_exif_data(img)

            # 获取GPS位置
            gps_location = get_gps_location(exif_data)

            # 获取拍摄日期
            date_taken = None
            if exif_data.get("DateTimeOriginal"):
                date_str = exif_data["DateTimeOriginal"]
                try:
                    date_taken = datetime.datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
                except:
                    date_taken = date_str.replace(":", "-", 2)

            # 创建预览图
            thumbnail_path = create_thumbnail(image_path, os.path.join(base_dir, THUMBNAIL_DIR))

            # 使用相对路径处理缩略图
            rel_thumbnail = os.path.relpath(thumbnail_path, base_dir) if thumbnail_path else None

            return {
                "filename": os.path.basename(image_path),
                "path": ipfs_url,  # IPFS网关链接
                "thumbnail": rel_thumbnail.replace("\\", "/") if rel_thumbnail else None,
                "width": width,
                "height": height,
                "date_taken": date_taken,
                "gps": gps_location
            }
    except Exception as e:
        print(f"处理图像 {image_path} 时出错: {e}")
        return None


def generate_panorama_index(directory, output_file):
    """生成全景图像索引"""
    print(f"开始扫描目录: {directory}")

    # 确保目录路径标准化
    base_dir = os.path.abspath(directory)

    # 清空并重建预览图目录
    thumb_dir = os.path.join(base_dir, THUMBNAIL_DIR)
    if os.path.exists(thumb_dir):
        shutil.rmtree(thumb_dir)
    os.makedirs(thumb_dir, exist_ok=True)

    # 查找所有JPEG文件
    image_files = []
    for root, dirs, files in os.walk(base_dir):
        # 跳过预览图目录
        if os.path.basename(root) == THUMBNAIL_DIR:
            continue

        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg')):
                image_files.append(os.path.join(root, file))

    print(f"找到 {len(image_files)} 个JPEG文件")

    # 处理所有图像
    panorama_data = []
    valid_count = 0
    for i, image_path in enumerate(image_files):
        print(f"处理中 [{i + 1}/{len(image_files)}]: {os.path.basename(image_path)}")
        img_info = get_image_info(image_path, base_dir)
        if img_info:
            panorama_data.append(img_info)
            if img_info.get("gps"):
                valid_count += 1

    print(f"成功处理 {len(panorama_data)} 个图像 ({valid_count} 个带GPS信息)")

    # 保存到JSON文件
    with open(os.path.join(base_dir, output_file), 'w') as f:
        json.dump(panorama_data, f, indent=2)

    print(f"索引已保存到: {os.path.join(base_dir, output_file)}")
    print(f"预览图保存到: {thumb_dir}")
    print("完成!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='全景图像索引生成工具（增强版）')
    parser.add_argument('directory', nargs='?', default='.',
                        help='要扫描的目录（默认为当前目录）')
    parser.add_argument('-o', '--output', default='panorama_index.json',
                        help='输出文件名（默认为panorama_index.json）')

    args = parser.parse_args()

    generate_panorama_index(args.directory, args.output)

