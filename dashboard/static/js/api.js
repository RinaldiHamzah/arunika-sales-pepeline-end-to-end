/** Batas komunikasi HTTP. Batas waktu berlaku untuk header dan isi respons. */
export async function requestJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    let data;
    try {
      data = await response.json();
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      throw new Error(`Server mengirim respons yang tidak dapat dibaca (HTTP ${response.status}, ${url.split('?')[0]}). Periksa log dashboard.`);
    }
    if (!response.ok) {
      if (response.status === 409 && data.status === 'already_running') return data;
      throw new Error(data.error || 'Permintaan gagal. Silakan coba lagi.');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Respons lebih dari 20 detik. Periksa koneksi lalu coba lagi.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
