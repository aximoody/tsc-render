# TheSecretCodex — Render Engine (Creatomate yerine)

Ücretsiz, kalıcı, filigransız render. GitHub Actions üzerinde FFmpeg ile 9:16 dikey
Shorts/Reels üretir: sahne klipleri + altyazı + müzik + (ElevenLabs) seslendirme.

## Zincir
```
Make: Gemini → Pexels  ──(repository_dispatch)──►  GitHub Actions
                                                     ├─ tts.py     (ElevenLabs seslendirme)
                                                     ├─ render.py  (FFmpeg montaj)
                                                     ├─ release     (biten mp4 → public URL)
                                                     └─ callback   ──► Make webhook
Make (2. senaryo): webhook → HTTP Download → YouTube + Instagram
```

## Kurulum (tek seferlik — SENDE olan adımlar)

1. **Repo oluştur** (private olabilir): bu klasörün içeriğini yeni bir GitHub repo'ya koy.
2. **Müzik ekle:** `music/` klasörüne 2-5 telifsiz `.mp3` at (bkz. `music/README.txt`).
3. **Secrets ekle** (repo → Settings → Secrets and variables → Actions):
   - `ELEVENLABS_API_KEY` — elevenlabs.io hesabından (voiceover için; sonra ekleyebilirsin, boşken müzik-only çalışır)
   - `ELEVENLABS_VOICE_ID` — opsiyonel (boşsa varsayılan anlatıcı ses)
4. **GitHub token** (Make'in Actions'ı tetiklemesi için): Settings → Developer settings →
   Personal access tokens → Fine-grained → bu repo'ya `Contents: Read/Write` +
   `Actions: Read/Write`. Token'ı Make'e yapıştıracaksın.

## Make tarafı (bunu ben kuracağım, tarayıcıdan)

- **1. senaryo** (mevcut, 18:00): Creatomate + HTTP Download + YouTube modüllerini SÖKÜP
  yerine tek bir HTTP modülü:
  ```
  POST https://api.github.com/repos/<KULLANICI>/<REPO>/dispatches
  Header: Authorization: Bearer <TOKEN>,  Accept: application/vnd.github+json
  Body:  {"event_type":"render_video","client_payload":{...}}
  ```
  `client_payload`: title, scenes[{text,clip,duration}], caption, hashtags, callback_url.
- **2. senaryo** (yeni, webhook tetikli): callback_url = bu webhook. Gelen `video_url`'i
  HTTP Download → YouTube upload (+ Instagram dalı) yapar.

## Manuel test
Actions sekmesi → "render-short" → Run workflow (workflow_dispatch). ElevenLabs key +
music koyduktan sonra `job.example.json` mantığıyla gerçek bir Pexels klip URL'iyle dene.

## Dosyalar
- `render.py` — FFmpeg motoru (9:16, altyazı yakma, müzik+ses miksi). **Test edildi, çalışıyor.**
- `tts.py` — ElevenLabs sahne-bazlı seslendirme; sahne sürelerini konuşmaya göre ayarlar.
- `build_job.py` — Make payload'unu job.json'a çevirir, müziği rastgele seçer.
- `.github/workflows/render.yml` — tetik→tts→render→release→callback.
