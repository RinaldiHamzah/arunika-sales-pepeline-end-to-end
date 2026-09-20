import argparse
import os
import time

from pyngrok import ngrok

PORT = 8501
NGROK_URL_FILE = "url.txt"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jalankan ngrok tunnel ke Flask di port 8501.")
    parser.add_argument("--token", "-t", help="Ngrok auth token. Jika tidak diberikan, akan membaca dari NGROK_AUTH_TOKEN.")
    args = parser.parse_args()

    auth_token = args.token or os.getenv("NGROK_AUTH_TOKEN")
    if not auth_token:
        raise RuntimeError(
            "NGROK_AUTH_TOKEN belum diset dan token tidak diberikan. "
            "Gunakan salah satu metode berikut:\n"
            "1) Set token di PowerShell saat ini:\n"
            "   $env:NGROK_AUTH_TOKEN = \"<token-anda>\"\n"
            "   python ngrok.py\n"
            "2) Jalankan langsung dengan argumen token:\n"
            "   python ngrok.py --token <token-anda>\n")
    try:
        ngrok.set_auth_token(auth_token)
        public_url = ngrok.connect(PORT, "http")
        url = public_url.public_url
        print(f"ngrok public URL: {url}")
        with open(NGROK_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url)
        print(f"URL tersimpan di {NGROK_URL_FILE}")
        print("Tekan CTRL+C untuk menghentikan tunnel.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Menghentikan ngrok tunnel...")
        ngrok.kill()
    except Exception as e:
        print(f"Gagal menjalankan ngrok: {e}")
        raise

#python ngrok.py --token
