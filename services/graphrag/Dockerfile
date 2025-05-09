FROM python:3.12
COPY . .
RUN apt-get update && apt-get install libgl1-mesa-glx ffmpeg libsm6 libxext6 cmake -y
RUN apt-get install libprotobuf-dev protobuf-compiler -y
RUN export CMAKE_ARGS="-DONNX_USE_PROTOBUF_SHARED_LIBS=ON"
RUN pip3 install keyrings.google-artifactregistry-auth==1.0.0
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 80
CMD ["python", "main.py"]
