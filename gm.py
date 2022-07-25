#!/usr/bin/python3
import pwd
import time
import docker
import argparse
import threading
import subprocess
from flask_cors import CORS
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, render_template


app = Flask(__name__)
CORS(app, supports_credentials=True)
process_list = None
gpu_status = None
gpu_status_history = []
mutex_process_list = threading.Lock()
mutex_gpu_status = threading.Lock()
mutex_gpu_status_history = threading.Lock()
gpu_number = -1


def get_gpu_number():
    """获取GPU的数量"""
    nvidia_smi_xml = nvidia_smi()
    return len(nvidia_smi_xml.findall("gpu"))


def owner(pid):
    '''返回进程所属的用户名'''
    try:
        for ln in open(f"/proc/{pid}/status"):
            if ln.startswith('Uid:'):
                uid = int(ln.split()[1])
                return pwd.getpwuid(uid).pw_name
    except FileNotFoundError:
        return ""


def nvidia_smi():
    """执行nvidia-smi -q -x命令获取返回的xml文本"""
    xml = subprocess.check_output(['nvidia-smi', '-q', '-x'])
    return ET.fromstring(xml)


def get_process_list(nvidia_smi_xml):
    """获取进程列表"""
    pid_to_container = {}
    client = docker.from_env()
    for c in client.containers.list():
        processes = c.top().get("Processes")
        for p in processes:
            pid_to_container[p[1]] = c.name
    processes = []
    for gpu_id, gpu in enumerate(nvidia_smi_xml.findall("gpu")):
        for process_info in gpu.findall(".//process_info"):
            pid = process_info.find("pid").text
            if pid in pid_to_container:
                user = f"{pid_to_container[pid]}"
                process_type = "container"   # 容器里面的进程
            else:
                user = f"{owner(pid)}"
                process_type = "host"        # 宿主机进程
            process = {
                "GPU": gpu_id,
                "PID": pid,
                "Process Name": process_info.find("process_name").text,
                "GPU Memory Usage": process_info.find("used_memory").text,
                "Type": process_type,
                "User": user,
            }
            processes.append(process)
    return processes


def get_gpu_status(nvidia_smi_xml):
    """获取显卡状态：温度、显存占用、显卡占用、功耗等"""
    status_list = []
    for gpu_id, gpu in enumerate(nvidia_smi_xml.findall("gpu")):
        status_list.append({
            # "gpu_id": gpu_id,
            # "product_name": gpu.find("product_name").text,
            "fan-speed": int(gpu.find("fan_speed").text.split()[0]),
            # "memory_total": int(gpu.find("fb_memory_usage/total").text.split()[0]),
            "memory-used": int(gpu.find("fb_memory_usage/used").text.split()[0]),
            "utilization": int(gpu.find("utilization/gpu_util").text.split()[0]),
            "temperature": int(gpu.find("temperature/gpu_temp").text.split()[0]),
            # "power_limit": float(gpu.find("power_readings/power_limit").text.split()[0]),
            "power-draw": float(gpu.find("power_readings/power_draw").text.split()[0]),
            # "power_state": gpu.find("power_readings/power_state").text,
            # "process_number": len(gpu.findall(".//process_info")),
        })
    data = {
        "timestamp": int(round(time.time())) * 1000,  # 将秒级时间戳转为毫秒级
        # "driver_version": nvidia_smi_xml.find("driver_version").text,
        # "cuda_version": nvidia_smi_xml.find("cuda_version").text,
        # "attached_gpus": int(nvidia_smi_xml.find("attached_gpus").text),
        "status": status_list
    }
    return data


def refresh():
    """每间隔一定时间获取一次信息"""
    global process_list
    global gpu_status
    global gpu_status_history
    one_hour = 60 * 60 * 1000  # 一小时的毫秒数
    while True:
        nvidia_smi_xml = nvidia_smi()
        # 刷新GPU状态
        gpu_status_temp = get_gpu_status(nvidia_smi_xml)
        mutex_gpu_status.acquire()
        gpu_status = gpu_status_temp
        mutex_gpu_status.release()
        # 刷新GPU状态历史列表
        mutex_gpu_status_history.acquire()
        if len(gpu_status_history) > 0 and gpu_status_history[-1]["timestamp"] == gpu_status_temp["timestamp"]:
            gpu_status_history[-1] = gpu_status_temp
        else:
            gpu_status_history.append(gpu_status_temp)
            # 只保留一个小时的历史
            while True:
                if gpu_status_history[-1]["timestamp"] - gpu_status_history[0]["timestamp"] > one_hour:
                    gpu_status_history = gpu_status_history[1:]
                else:
                    break
        mutex_gpu_status_history.release()
        # 刷新进程列表
        mutex_process_list.acquire()
        process_list = get_process_list(nvidia_smi_xml)
        mutex_process_list.release()


@app.route("/")
@app.route("/index.html")
def api_index_html():
    return render_template("index.html")


@app.route("/smi.html")
def api_smi_html():
    return render_template("smi.html")


@app.route("/process.html")
def api_process_html():
    return render_template("process.html")


@app.route("/nvidia-smi")
def api_nvidia_smi():
    return subprocess.check_output(['nvidia-smi'])


@app.route("/process")
def api_process():
    mutex_process_list.acquire()
    temp = process_list
    mutex_process_list.release()
    return jsonify(temp)


@app.route("/status")
def api_status():
    mutex_gpu_status.acquire()
    temp = gpu_status
    mutex_gpu_status.release()
    return jsonify(temp)


@app.route("/status-history")
def api_status_history():
    mutex_gpu_status_history.acquire()
    temp = gpu_status_history
    mutex_gpu_status_history.release()
    return jsonify(temp)


@app.route("/gpu-number")
def api_gpu_number():
    global gpu_number
    if gpu_number < 0:
        gpu_number = get_gpu_number()
    return str(gpu_number)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("GPU Moniter")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    threading.Thread(target=refresh).start()
    app.run(host=args.host, port=args.port, debug=args.debug)
