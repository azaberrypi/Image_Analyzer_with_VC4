#coding:utf-8
import sys
import io
import numpy as np
from PIL import Image, ImageFilter

from videocore.assembler import qpu
from videocore.driver import Driver

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

def mask(idx):
    values = [1]*16
    values[idx] = 0
    return values

@qpu
def histogram_rgb(asm):

    # ここはC言語のマクロ的な使い方
    IN_ADDR   = 0 #インデックス
    OUT_ADDR  = 1
    IO_ITER   = 2
    THR_ID    = 3
    THR_NM    = 4
    OUT_G_ADDR = 5
    OUT_B_ADDR = 6
    COMPLETED = 0 #セマフォ用

    ldi(rb[31], 1) # 色識別用

    ldi(null,mask(IN_ADDR),set_flags=True)  # 次の行でr2にuniformの任意の場所を格納するためにzero flagセット
    mov(r2,uniform,cond='zs')
    ldi(null,mask(OUT_ADDR),set_flags=True)
    mov(r2,uniform,cond='zs')
    #ldi(null,mask(IO_ITER),set_flags=True)
    #mov(r2,uniform,cond='zs')
    ldi(null,mask(THR_ID),set_flags=True)
    mov(r2,uniform,cond='zs')
    ldi(null,mask(THR_NM),set_flags=True)
    mov(r2,uniform,cond='zs')
    ldi(null,mask(OUT_G_ADDR),set_flags=True)
    mov(r2,uniform,cond='zs')
    ldi(null,mask(OUT_B_ADDR),set_flags=True)
    mov(r2,uniform,cond='zs')


    ldi(r1, 16)
    imul24(r3,element_number,r1)   # 24bitの掛け算 第3引数を4→16にすることで、Rの値のみがとれる [0,16,32,48,64...,240]
    rotate(broadcast,r2,-IN_ADDR) # rotate と broadcast のあわせ技!! GPU本p47 r5に格納
    iadd(r0,r5,r3)  # integer add    # これでin_addrを先頭とした16要素=64bytesのアドレスが格納される
    jmp(L.get_brightness)
    nop()
    nop()
    nop()

    L.green
    ldi(r1, 16)
    imul24(r3,element_number,r1)   # 24bitの掛け算 第3引数を4→16にすることで、Rの値のみがとれる [0,16,32,48,64...,240]
    iadd(r3, r3, 4)     # これでGの値のみがとれる [4,20,36,52,68...,244]
    rotate(broadcast,r2,-IN_ADDR) # rotate と broadcast のあわせ技!! GPU本p47 r5に格納
    iadd(r0,r5,r3)  # integer add    # これでin_addrを先頭とした16要素=64bytesのアドレスが格納される
    jmp(L.get_brightness)
    nop()
    nop()
    nop()

    L.blue
    ldi(r1, 16)
    imul24(r3,element_number,r1)   # 24bitの掛け算 第3引数を4→16にすることで、Rの値のみがとれる [0,16,32,48,64...,240]
    iadd(r3, r3, 8)     # これでBの値のみがとれる[8,24,40,56,72,...,248]
    rotate(broadcast,r2,-IN_ADDR) # rotate と broadcast のあわせ技!! GPU本p47 r5に格納
    iadd(r0,r5,r3)  # integer add    # これでin_addrを先頭とした16要素=64bytesのアドレスが格納される


    L.get_brightness
    ldi(r1, 0) # r1を明度カウンターとして扱う

    # ここでIO_ITERの初期化
    ldi(null,mask(IO_ITER),set_flags=True)
    mov(r2,uniform,cond='zs')

    L.loop

    ldi(broadcast,16*4*4) # r5に格納

    # レジスタファイル30x2個のそれぞれに16要素格納できるため、一気に格納
    for i in range(30):
        #ra
        mov(tmu0_s,r0) # r0に入っているアドレスを TMU に読んでもらうアドレスに指定
        nop(sig='load tmu0') # TMU の読み込みをリクエスト, r4に格納
        iadd(r0,r0,r5)  # 入力画像の読む位置を更新
        mov(ra[i],r4)

        #rb
        mov(tmu1_s,r0)
        nop(sig='load tmu1')
        iadd(r0,r0,r5)
        mov(rb[i],r4)

    for histogram in range(16): # 16回roop 256/16段階で明度を記録
        ldi(broadcast, 16) # r5を16で埋める
        ldi(r3, 0)  # r3を一時的なカウンターとして扱う
        for register_file in range(30): # 30回roop ra,rbのそれぞれの総数
            # ra rb全てから16を引いていく
            # マイナスになっている箇所のみインクリメント
            isub(ra[register_file], ra[register_file], r5, set_flags=True)
            iadd(r3, r3, 1, cond='ns')
            isub(rb[register_file], rb[register_file], r5, set_flags=True)
            iadd(r3, r3, 1, cond='ns')

        # r1の要素をr0のhistogramの各明度の場所に足していく
        ldi(null, mask(histogram) ,set_flags=True) # r0のhistogram番目にzfを立てる
        for i in range(16): # 16回roop レジスタ1個当たり16要素あるため
            rotate(broadcast, r3, -i, set_flags=False)   # r3のi番目の要素をr5に書き込む
            iadd(r1, r1, r5, cond='zs', set_flags=False)

    ldi(null,mask(IO_ITER),set_flags=True) # 次の行のためにzfを立てる
    isub(r2,r2,4,cond='zs') #r2の中のIO_ITER（転送回数）にのみ、4を引いてr2に格納 NOTFIXME
    jzc(L.loop)     # Jump if Z-flags are clear, r2がゼロじゃない
    nop()
    nop()
    nop()

    mutex_acquire() # VPMを触り始める時の命令
    # rotate の第3引数は即値じゃないとダメみたい

    # どの値をbroadcastに格納するかを決める
    if(1):
        mov(r3, rb[31])     # r3の初期化
        iadd(null, r3, -1, set_flags=True)
        jzs(L.start_setup_vpm_write)
        rotate(broadcast, r2, -OUT_ADDR) # OUT_ADDRの先頭アドレスでr5を埋める #nop()
        nop()
        nop()

        iadd(null, r3, -5, set_flags=True)
        jzs(L.start_setup_vpm_write)
        rotate(broadcast, r2, -OUT_G_ADDR) # OUT_G_ADDRの先頭アドレスでr5を埋める #nop()
        nop()
        nop()

        rotate(broadcast, r2, -OUT_B_ADDR) # OUT_G_ADDRの先頭アドレスでr5を埋める #nop()

    L.start_setup_vpm_write

    setup_vpm_write(mode='32bit horizontal',Y=0,X=0)

    mov(vpm, r1)

    setup_dma_store(mode='32bit horizontal',Y=0, nrows=1)
    start_dma_store(r5)
    wait_dma_store()

    mutex_release()

    """
    ここでホストプログラムに戻る処理をせずに、色の変更をさせたい
    """

    mov(r3, rb[31])
    iadd(null, r3, -1, set_flags=True)
    jzs(L.green)
    ldi(rb[31], OUT_G_ADDR) #nop()
    nop()
    nop()

    iadd(null, r3, -5, set_flags=True)
    jzs(L.blue)
    ldi(rb[31], OUT_B_ADDR) #nop()
    nop()
    nop()


#====semaphore=====
    sema_up(COMPLETED)  # それぞれのqpuが、処理が終わったらここに来てセマフォをあげる
    rotate(broadcast,r2,-THR_ID)    # r2の3番目の値でr5を埋める
    iadd(null,r5,-1,set_flags=True)
    jzc(L.skip_fin) # QPU1だけこの処理をスキップしたいという話
    nop()
    nop()
    nop()
    rotate(broadcast,r2,-THR_NM)    # r2の4番目の値でr5を埋める
    iadd(r0, r5, -1,set_flags=True)
    L.sem_down
    jzc(L.sem_down) # zero flag clear
    sema_down(COMPLETED)    # 他のスレッドが終了するまで待つ
    nop()
    iadd(r0, r0, -1)    # ここのフラグでjzc(L.sem_down)の判定がされる

    interrupt()     # qpu1がここにたどり着いたらGPUの処理が終わりでホストプログラムに戻る

    L.skip_fin

    exit(interrupt=False)   # 他のqpuの処理が終わらないようにFalse



with Driver() as drv:

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
    overlay_dstimg2 = camera.PiCameraOverlay(cam, 5)
    overlay_dstimg3 = camera.PiCameraOverlay(cam, 6)
    #cam.start_preview(fullscreen=False, window=(0, 0, WINDOW_W, H*2))    # window:始点x,始点y,サイズx,サイズy      # 入力画像を画面描画している

    # 画面のクリア
    back_img = Image.new('RGBA', (DISPLAY_W, DISPLAY_H), 0)
    hdmi.printImg(back_img, *hdmi.getResolution(), hdmi.PUT)

    n_threads=12
    SIMD=16
    R=60    # 使用するra,rbレジスタの数, max:64

    th_H    = int(H/n_threads) #1スレッドの担当行
    th_ele  = th_H*W*4 #1スレッドの担当要素
    io_iter = int(th_ele/(R*SIMD)) #何回転送するか

    print(th_H, th_ele, io_iter)

    IN  = drv.alloc((H,W,4),'uint32')
    OUT = drv.alloc((n_threads,16),'uint32')
    OUT[:] = 0.0
    OUT_G = drv.alloc((n_threads,16),'uint32')
    OUT_G[:] = 0.0
    OUT_B = drv.alloc((n_threads,16),'uint32')
    OUT_B[:] = 0.0

    # ここで既にスレッドごとに処理する部分を分けている
    uniforms=drv.alloc((n_threads,9),'uint32')
    for th in range(n_threads):
        uniforms[th,0]=IN.address + (th_ele * 4 * th)
        uniforms[th,1]=OUT.addresses()[th,0]
        uniforms[th,4]=OUT_G.addresses()[th,0]
        uniforms[th,5]=OUT_B.addresses()[th,0]
    uniforms[:,2]=np.arange(1,(n_threads+1))    #[1,2,...,13]
    uniforms[:,3]=n_threads
    uniforms[:,6]=int(io_iter)
    uniforms[:,7]=int(io_iter)
    uniforms[:,8]=int(io_iter)

    code=drv.program(histogram_rgb)

    try:
        fps = FPS()
        stream = io.BytesIO()
        while True:
            input_img_RGB = camera.capture2PIL(cam, stream, (320, 368))
            input_img = input_img_RGB.convert('RGBA')
            pil_img = input_img.resize((W, H))

            IN[:] = np.asarray(pil_img)[:]

            drv.execute(
                n_threads= n_threads,
                program  = code,
                uniforms = uniforms
            )

            # ヒストグラムを作るための処理
            sum = [0] * SIMD
            sum_g = [0] * SIMD
            sum_b = [0] * SIMD
            for i in range(n_threads):
                for j in range(SIMD):
                    sum[j] += OUT[i][j]
                    sum_g[j] += OUT_G[i][j]
                    sum_b[j] += OUT_B[i][j]

            for i in range(SIMD):
                temp = sum[i]
                temp_g = sum_g[i]
                temp_b = sum_b[i]
                for j in range(SIMD-1, i, -1):
                    sum[j] -= temp
                    sum_g[j] -= temp_g
                    sum_b[j] -= temp_b

            #print("ok")    # for debug


            draw_img = Image.new('RGB', (DISPLAY_W, DISPLAY_H - H*2), 0)    # NOTE:alpha値にも拡張したいときはRGBAにする   # 第二引数はサイズ

            hdmi.addText_64(draw_img, *(0, 64 * 0 + 20), "Raspberry Pi")   # draw_img上での位置
            hdmi.addColoredText_64(draw_img, *(550, 64 * 0 + 20), "VideoCore IV", "red")

            hdmi.addText_64(draw_img, *(0, 64 * 2 + 20), f'{H}x{W}')

            hdmi.addText_64(draw_img, *(0, 64 * 4 + 20), "Histogram")
            hdmi.addText_64(draw_img, *(400, 64 * 4 + 20), "in 16 levels")

            hdmi.addText_64(draw_img, *(0, 64 * 6 + 20), f'{fps.update():.3f} FPS')


            draw_img = draw_img.convert('RGB')
            overlay_dstimg.OnOverlayUpdated(draw_img, format='rgb', fullscreen=False, window=(0, H*2, DISPLAY_W, DISPLAY_H - H*2))



            histogram_img = Image.new('RGB', (WINDOW_W, H*2), 0)    # 第二引数で大きさを指定
            histogram_green_img = Image.new('RGB', (WINDOW_W, H*2) ,0)
            histogram_blue_img = Image.new('RGB', (WINDOW_W, H*2) ,0)

            # ヒストグラム各要素に対してRectangleを作る
            for i in range(16):
                hdmi.printColoredRectangle(histogram_img, "red", i*(WINDOW_W/16), H*2 - (sum[i] * (H*2 / 115200)), (i+1)*(WINDOW_W/16), H*2)    # 第2~引数で位置を指定
                hdmi.printColoredRectangle(histogram_green_img, "green", i*(WINDOW_W/16), H*2 - (sum_g[i] * (H*2 / 115200)), (i+1)*(WINDOW_W/16), H*2)    # 第2~引数で位置を指定
                hdmi.printColoredRectangle(histogram_blue_img, "blue", i*(WINDOW_W/16), H*2 - (sum_b[i] * (H*2 / 115200)), (i+1)*(WINDOW_W/16), H*2)    # 第2~引数で位置を指定


            overlay_dstimg1.OnOverlayUpdated(histogram_img, format='rgb', fullscreen=False, window=(0, 0, WINDOW_W, H*2))
            overlay_dstimg2.OnOverlayUpdated(histogram_green_img, format='rgb', fullscreen=False, window=(WINDOW_W, 0, WINDOW_W, H*2))
            overlay_dstimg3.OnOverlayUpdated(histogram_blue_img, format='rgb', fullscreen=False, window=(WINDOW_W*2, 0, WINDOW_W, H*2))

    except KeyboardInterrupt:
        # Ctrl-C を捕まえた！
        print('\nCtrl-C is pressed, end of execution!')
        cam.stop_preview()
        cam.close()
