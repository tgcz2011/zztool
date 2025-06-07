#!/usr/bin/env python3
"""
全景图像索引生成工具（增强版）
自动扫描目录、生成预览图、创建索引文件
"""

import os
import json
import argparse
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import datetime
import shutil

# 配置参数
THUMBNAIL_SIZE = (320, 180)  # 预览图尺寸
THUMBNAIL_DIR = "thumbnails"  # 预览图子目录


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
    """获取图像信息，包括尺寸、日期和GPS位置"""
    try:
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

            # 使用相对路径
            rel_path = os.path.relpath(image_path, base_dir)
            rel_thumbnail = os.path.relpath(thumbnail_path, base_dir) if thumbnail_path else None

            return {
                "filename": os.path.basename(image_path),
                "path": rel_path.replace("\\", "/"),  # 确保使用正斜杠
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