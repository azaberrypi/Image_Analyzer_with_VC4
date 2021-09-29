#coding:utf-8
import sys
import io
import numpy as np
from PIL import Image, ImageFilter

from time import sleep, clock_gettime, CLOCK_MONOTONIC
import picamera.array
from picamera import PiCamera

sys.path.append("./00_utils/")
import hdmi
import camera
from fps import FPS

def setCamera(w, h):
  camera = PiCamera()
  camera.resolution = (w, h)

  return camera

DISPLAY_W, DISPLAY_H = hdmi.getResolution()
WINDOW_W = DISPLAY_W // 3  # ディスプレイを3分割
#WINDOW_H = DISPLAY_H

# 画像サイズ
H=360
W=320

# cameraセットアップ
cam = camera.setCamera(320, 368)
cam.framerate = 30
overlay_dstimg = camera.PiCameraOverlay(cam, 3)
overlay_dstimg1 = camera.PiCameraOverlay(cam, 4)
cam.start_preview(fullscreen=False, window=(0, 0, WINDOW_W, H*2))    # window:始点x,始点y,サイズx,サイズy

# 画面のクリア
back_img = Image.new('RGBA', (DISPLAY_W, DISPLAY_H), 0)
hdmi.printImg(back_img, *hdmi.getResolution(), hdmi.PUT)

try:
    fps = FPS()
    stream = io.BytesIO()
    while True:
        input_img_RGB = camera.capture2PIL(cam, stream, (320, 368))
        input_img = input_img_RGB.convert('RGBA')
        pil_img = input_img.resize((W, H))

        IN = np.asarray(pil_img)

        # OUTに各Rの明度を16段階に振り分けて、段階ごとの個数を格納していく
        OUT = [0] * 16
        for i in range(H):
            for j in range(W):
                OUT[IN[i][j][0] // 16] += 1                


        draw_img = Image.new('RGB', (WINDOW_W, H), 0)   # 第二引数はサイズ
        
        hdmi.addText(draw_img, *(10, 32 * 0), "Raspberry Pi")   # draw_img上での位置
        hdmi.addColoredText(draw_img, *(10, 32 * 1), "Cortex-A53", "red")

        hdmi.addText(draw_img, *(10, 32 * 3), f'{H}x{W}')
        
        hdmi.addText(draw_img, *(10, 32 * 5), "Histogram")
        hdmi.addText(draw_img, *(10, 32 * 6), "in 16 levels")

        hdmi.addText(draw_img, *(10, 32 * 8), f'{fps.update():.3f} FPS')
        

        draw_img = draw_img.convert('RGB')
        overlay_dstimg.OnOverlayUpdated(draw_img, format='rgb', fullscreen=False, window=(WINDOW_W*2, 0, WINDOW_W*2, H*2))

        
        histogram_img = Image.new('RGB', (WINDOW_W, H*2), 0)    # 第二引数で大きさを指定
        
        # ヒストグラム各要素に対してRectangleを作る
        for i in range(16):
            hdmi.printColoredRectangle(histogram_img, "red", i*(WINDOW_W/16), H*2 - (OUT[i] * (H*2 / 115200)), (i+1)*(WINDOW_W/16), H*2)    # 第2~引数で位置を指定
        
        overlay_dstimg1.OnOverlayUpdated(histogram_img, format='rgb', fullscreen=False, window=(WINDOW_W, 0, WINDOW_W, H*2))


except KeyboardInterrupt:
    # Ctrl-C を捕まえた！
    print('\nCtrl-C is pressed, end of execution!')
    cam.stop_preview()
    cam.close()
