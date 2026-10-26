import os
import re
import time
import json
import asyncio
import numpy as np
import PIL.Image
from gtts import gTTS

# ปลั๊กอินแก้ปัญหา Pillow v10+ ยกเลิกคำว่า ANTIALIAS สำหรับ MoviePy 1.0.3
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = getattr(PIL.Image, 'LANCZOS', PIL.Image.BICUBIC)

import streamlit as st
from google import genai
from elevenlabs.client import ElevenLabs
import edge_tts
import yt_dlp
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปเล่าเรื่องตัดฉากอัตโนมัติ")
st.write("สรุปวิดีโอ เล่าเรื่องสนุก ตัดฉากตรงภาพ พร้อมตัวเลือกเสียงพากย์ครบทุกสไตล์!")

# ดึง API Key จาก Streamlit Secrets
raw_api_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = str(raw_api_key).strip().strip('"').strip("'")
eleven_api_key = st.secrets.get("ELEVENLABS_API_KEY", "").strip().strip('"').strip("'")

# ตัวเลือกนำเข้าวิดีโอ
option = st.radio("เลือกวิธีนำเข้าวิดีโอ:", ["อัปโหลดไฟล์วิดีโอ (.mp4)", "วางลิงก์ TikTok"])

uploaded_file = None
video_url = ""

if option == "อัปโหลดไฟล์วิดีโอ (.mp4)":
    uploaded_file = st.file_uploader("เลือกไฟล์วิดีโอจากเครื่อง (มือถือ/คอม):", type=["mp4", "mov"])
else:
    video_url = st.text_input("วางลิงก์ TikTok:")

aspect_ratio = st.selectbox("เลือกขนาดวิดีโอ:", ["แนวตั้ง (9:16)", "แนวนอน (16:9)"])
duration_option = st.selectbox("เลือกความยาวสคริปต์และคลิป:", ["30 วินาที", "1 นาที", "2 นาที", "3 นาที", "5 นาที"])

# ศูนย์รวมตัวเลือกโมเดลเสียงพากย์ทุกรูปแบบ
voice_selection = st.selectbox(
    "เลือกโมเดลเสียงพากย์ (Voice Engine):", 
    [
        "🌟 ElevenLabs: Adam (เสียงชาย - มนุษย์จริง เนียนใส่อารมณ์)",
        "🌟 ElevenLabs: Rachel (เสียงหญิง - มนุษย์จริง สดใสมีพลัง)",
        "🌟 ElevenLabs: Charlie (เสียงชาย - มนุษย์จริง สายสปอยล์)",
        "⚡ Edge-TTS: ผู้หญิงสายเล่าเรื่อง (Premwadee - สปีดเร่ง +12% สนุกกระชับ ฟรี)",
        "⚡ Edge-TTS: ผู้ชายสายสปอยล์ (Niwat - สปีดเร่ง +12% เสียงหนักแน่น ฟรี)",
        "🔊 Google Voice: (gTTS - ภาษาไทยมาตรฐาน อ่านชัด ฟรี 100%)"
    ]
)

# ฟังก์ชันดึงวิดีโอสำหรับ TikTok
def download_tiktok(url, output_path="input_video.mp4"):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'overwrites': True,
        'nocheckcertificate': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

# ฟังก์ชันแปลงคำอ่านภาษาอังกฤษเป็นภาษาไทยให้ AI อ่านเป๊ะ
def clean_text_for_tts(text):
    if not text:
        return "มาดูคลิปนี้กันครับ"
    
    word_map = {
        "Mr. Crab": "มิสเตอร์แครปส์",
        "Mr.Crab": "มิสเตอร์แครปส์",
        "Mr. Krabs": "มิสเตอร์แครปส์",
        "SpongeBob": "สปอนจ์บอบ",
        "Patrick": "แพทริก",
        "TikTok": "ติ๊กต็อก",
        "Facebook": "เฟซบุ๊ก",
        "YouTube": "ยูทูบ"
    }
    
    for k, v in word_map.items():
        text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
        
    text = re.sub(r'[\*\#\_\[\]\(\)\{\}\<\>]', '', text)
    text = re.sub(r'([\.\,\!\?])', r'\1 ', text)
    text = re.sub(r'[^\w\s\u0E00-\u0E7F]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if text else "มาดูคลิปนี้กันครับ"

# ฟังก์ชันจัดการสร้างเสียงพากย์ตามโมเดลที่เลือก
def generate_voice_audio(text, choice, output_file="voice.mp3"):
    clean_text = clean_text_for_tts(text)

    # 1. กลุ่มเสียง ElevenLabs
    if "ElevenLabs" in choice:
        if eleven_api_key:
            voice_id = "pNInz6obpgDQGcFmaJgB" # Adam Default
            if "Rachel" in choice:
                voice_id = "21m00Tcm4TlvDq8ikWAM"
            elif "Charlie" in choice:
                voice_id = "IKne3meq5aSn9XLyUdCD"

            try:
                client = ElevenLabs(api_key=eleven_api_key)
                audio = client.generate(
                    text=clean_text,
                    voice=voice_id,
                    model="eleven_multilingual_v2"
                )
                with open(output_file, "wb") as f:
                    for chunk in audio:
                        f.write(chunk)
                return
            except Exception:
                pass # หากมีข้อผิดพลาด ให้สลับไปใช้ Edge-TTS สำรองให้อัตโนมัติ

        # สำรองกรณีไม่ได้ใส่ ElevenLabs Key
        async def run_edge_fallback():
            communicate = edge_tts.Communicate(clean_text, "th-TH-PremwadeeNeural", rate="+12%", pitch="+2Hz")
            await communicate.save(output_file)
        asyncio.run(run_edge_fallback())

    # 2. กลุ่มเสียง Edge-TTS (ปรับแต่งสปีดตื่นเต้น)
    elif "Edge-TTS" in choice:
        voice_code = "th-TH-PremwadeeNeural" if "Premwadee" in choice else "th-TH-NiwatNeural"
        async def run_edge():
            communicate = edge_tts.Communicate(clean_text, voice_code, rate="+12%", pitch="+2Hz")
            await communicate.save(output_file)
        asyncio.run(run_edge())

    # 3. กลุ่มเสียง gTTS (Google Voice ฟรี 100%)
    else:
        tts = gTTS(text=clean_text, lang='th', slow=False)
        tts.save(output_file)

if st.button("🚀 เริ่มสร้างวิดีโอ"):
    if not api_key:
        st.error("ไม่พบ GEMINI_API_KEY ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud ก่อนครับ")
    elif option == "วางลิงก์ TikTok" and not video_url:
        st.warning("กรุณาใส่ลิงก์วิดีโอก่อนครับ")
    elif option == "อัปโหลดไฟล์วิดีโอ (.mp4)" and not uploaded_file:
        st.warning("กรุณาเลือกไฟล์วิดีโอจากเครื่องก่อนครับ")
    else:
        try:
            status = st.empty()
            video_file = "input_video.mp4"

            # 1. เตรียมไฟล์วิดีโอ
            if option == "อัปโหลดไฟล์วิดีโอ (.mp4)":
                status.info("📥 กำลังเตรียมไฟล์วิดีโอ...")
                with open(video_file, "wb") as f:
                    f.write(uploaded_file.read())
            else:
                status.info("📥 กำลังดาวน์โหลดวิดีโอ TikTok...")
                download_tiktok(video_url, video_file)
            
            # 2. ตั้งค่าเวลาและสร้างสคริปต์
            duration_word_map = {
                "30 วินาที": ("30 วินาที", 75),
                "1 นาที": ("1 นาที", 150),
                "2 นาที": ("2 นาที", 300),
                "3 นาที": ("3 นาที", 450),
                "5 นาที": ("5 นาที", 750),
            }
            time_label, target_words = duration_word_map.get(duration_option, ("30 วินาที", 75))

            status.info(f"🤖 Gemini กำลังวิเคราะห์ Timestamp ภาพและสร้างสคริปต์พากย์ ({time_label})...")
            client = genai.Client(api_key=api_key)
            g_file = client.files.upload(file=video_file)
            
            prompt = f"""
            สวมบทบาทเป็น "ครีเอเตอร์สายเล่าเรื่องสุดปั่น" ที่กำลังเล่าคลิปนี้ให้เพื่อนฟังแบบตื่นเต้นและใส่อารมณ์สุดๆ!
            แบ่งเนื้อหาออกเป็นฉากตาม Timestamp จริงในวิดีโอ ความยาวรวมประมาณ {time_label} (ประมาณ {target_words} คำ)

            ตอบกลับในรูปแบบ JSON Array เท่านั้น ห้ามมีข้อความอื่นนอกเหนือจาก JSON เช่น:
            [
              {{"start_sec": 0, "end_sec": 5, "text": "เฮ้ยทุกคน ดูช็อตนี้! เปิดมาก็เอาเลยว่ะ..."}},
              {{"start_sec": 6, "end_sec": 12, "text": "จังหวะนี้แหละ อย่างพีค..."}}
            ]

            กฎเหล็กการแต่งบทพากย์ ("text"):
            1. ใช้น้ำเสียงแบบเพื่อนเล่าเรื่องให้เพื่อนฟัง มีคำอุทานสร้างอารมณ์ เช่น "เฮ้ย!", "ว้าว!", "ดูสิ!", "จังหวะนี้คือ!"
            2. เขียนชื่อตัวละครเป็นคำอ่านไทยตรงตัว เช่น Mr. Krabs -> มิสเตอร์แครปส์, SpongeBob -> สปอนจ์บอบ
            3. สคริปต์ต้องตรงกับภาพที่เกิดขึ้นในช่วง start_sec ถึง end_sec นั้นๆ
            4. ห้ามมีอักขระพิเศษ (*, #) หรือสัญลักษณ์แปลกๆ
            """
            
            max_retries = 3
            response = None
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model='gemini-3.8-flash',
                        contents=[g_file, prompt]
                    )
                    if response and getattr(response, 'text', None):
                        break
                except Exception as api_err:
                    last_error = api_err
                    err_msg = str(api_err)
                    if "503" in err_msg or "UNAVAILABLE" in err_msg:
                        wait_time = (attempt + 1) * 3
                        status.warning(f"⏳ เซิร์ฟเวอร์ยุ่ง กำลังลองใหม่อัตโนมัติใน {wait_time} วินาที...")
                        time.sleep(wait_time)
                        continue
                    elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        raise Exception("โควตาฟรีประจำวันของ Gemini API Key นี้หมดแล้ว กรุณาเปลี่ยน API Key ใหม่ใน Streamlit Secrets ครับ")
                    else:
                        if attempt == max_retries - 1:
                            raise api_err
                        time.sleep(2)

            if not response or not getattr(response, 'text', None):
                raise Exception(f"ไม่สามารถเชื่อมต่อ Gemini API ได้: {str(last_error)}")

            raw_response_text = response.text.strip()
            clean_json_str = re.sub(r'```json\s*|\s*```', '', raw_response_text).strip()
            
            scenes = []
            try:
                scenes = json.loads(clean_json_str)
            except Exception:
                scenes = [{"start_sec": 0, "end_sec": 30, "text": raw_response_text}]

            st.subheader("📝 สคริปต์เล่าเรื่องแบบใส่อารมณ์:")
            full_script_display = ""
            for i, sc in enumerate(scenes, 1):
                full_script_display += f"**ฉากที่ {i} [{sc.get('start_sec', 0)}s - {sc.get('end_sec', 0)}s]:** {sc.get('text', '')}\n\n"
            st.markdown(full_script_display)

            # 3. เจนเสียงพากย์และตัดคลิปตาม Timestamp
            status.info("🎙️ กำลังลงเสียงพากย์ตามโมเดลที่เลือกและรวมฉาก...")
            main_clip = VideoFileClip(video_file)
            scene_clips = []

            for idx, sc in enumerate(scenes):
                text = sc.get('text', '')
                if not text.strip():
                    continue

                start_t = float(sc.get('start_sec', 0))
                end_t = float(sc.get('end_sec', start_t + 5))

                start_t = max(0.0, min(start_t, main_clip.duration - 0.5))
                end_t = max(start_t + 0.5, min(end_t, main_clip.duration))

                audio_file = f"voice_scene_{idx}.mp3"
                generate_voice_audio(text, voice_selection, audio_file)
                sc_audio = AudioFileClip(audio_file)

                sc_video = main_clip.subclip(start_t, end_t)

                if sc_video.duration < sc_audio.duration:
                    n_repeats = int(np.ceil(sc_audio.duration / sc_video.duration))
                    sc_video = concatenate_videoclips([sc_video] * n_repeats).subclip(0, sc_audio.duration)
                else:
                    sc_video = sc_video.subclip(0, sc_audio.duration)

                sc_video = sc_video.set_audio(sc_audio)
                scene_clips.append(sc_video)

            if not scene_clips:
                raise Exception("ไม่สามารถตัดแบ่งฉากวิดีโอได้ กรุณาลองใหม่อีกครั้ง")

            final_clip = concatenate_videoclips(scene_clips)
            
            target_w, target_h = (1080, 1920) if "แนวตั้ง" in aspect_ratio else (1920, 1080)
            final_clip = final_clip.resize(newsize=(target_w, target_h))

            output_filename = "output_video.mp4"
            final_clip.write_videofile(output_filename, codec='libx264', audio_codec='aac')

            status.success("🎉 ทำคลิปเสร็จเรียบร้อยแล้ว!")
            st.video(output_filename)
            
            with open(output_filename, "rb") as file:
                st.download_button(
                    label="⬇️ ดาวน์โหลดวิดีโอ (.mp4)",
                    data=file,
                    file_name="narrated_story_video.mp4",
                    mime="video/mp4"
                )

        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {str(e)}")
