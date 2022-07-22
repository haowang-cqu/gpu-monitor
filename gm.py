#!/usr/bin/python3
import pwd
import docker
import subprocess
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app, supports_credentials=True)
UID   = 1
EUID  = 2


def owner(pid):
    '''Return username of UID of process pid'''
    for ln in open(f"/proc/{pid}/status"):
        if ln.startswith('Uid:'):
            uid = int(ln.split()[UID])
            return pwd.getpwuid(uid).pw_name


def all_gpu_process():
    pid_to_container = {}
    client = docker.from_env()
    for c in client.containers.list():
        processes = c.top().get("Processes")
        for p in processes:
            pid_to_container[p[1]] = c.name

    nvidia_smi = subprocess.check_output(['nvidia-smi', '-q', '-x'])
    root = ET.fromstring(nvidia_smi)
    processes = []
    for gpu_id, gpu in enumerate(root.findall("gpu")):
        for process_info in gpu.findall(".//process_info"):
            pid = process_info.find("pid").text
            if pid in pid_to_container:
                user = f"{pid_to_container[pid]}"
                _type = "container"
            else:
                user = f"{owner(pid)}"
                # if user == "gdm":
                #     continue
                _type = "host"

            process = {
                "GPU": gpu_id,
                "PID": pid,
                "Process Name": process_info.find("process_name").text,
                "GPU Memory Usage": process_info.find("used_memory").text,
                "Type": _type,
                "User": user,
            }
            processes.append(process)
    return processes


@app.route("/")
@app.route("/index.html")
def index_html():
    return render_template("index.html")


@app.route("/smi.html")
def smi_html():
    return render_template("smi.html")


@app.route("/process.html")
def process_html():
    return render_template("process.html")


@app.route("/nvidia-smi")
def nvidia_smi():
    return subprocess.check_output(['nvidia-smi'])

@app.route("/process")
def process():
    return jsonify(all_gpu_process())

@app.route("/status")
def status():
    nvidia_smi = subprocess.check_output(['nvidia-smi', '-q', '-x'])
    root = ET.fromstring(nvidia_smi)
    status_list = []
    for gpu_id, gpu in enumerate(root.findall("gpu")):
        status_list.append({
            "gpu_id": gpu_id,
            "product_name": gpu.find("product_name").text,
            "fan_speed": int(gpu.find("fan_speed").text.split()[0]),
            "memory_total": int(gpu.find("fb_memory_usage/total").text.split()[0]),
            "memory_used": int(gpu.find("fb_memory_usage/used").text.split()[0]),
            "utilization": int(gpu.find("utilization/gpu_util").text.split()[0]),
            "temperature": int(gpu.find("temperature/gpu_temp").text.split()[0]),
            "power_limit": float(gpu.find("power_readings/power_limit").text.split()[0]),
            "power_draw": float(gpu.find("power_readings/power_draw").text.split()[0]),
            "power_state": gpu.find("power_readings/power_state").text,
            "process_number": len(gpu.findall(".//process_info")),
        })
    data = {
        "timestamp": root.find("timestamp").text,
        "driver_version": root.find("driver_version").text,
        "cuda_version": root.find("cuda_version").text,
        "attached_gpus": int(root.find("attached_gpus").text),
        "status": status_list
    }
    return jsonify(data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=12345)
