/** HTTP boundary. A timeout covers both headers and the response body. */
export async function requestJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 409 && data.status === 'already_running') return data;
      throw new Error(data.error || 'Permintaan gagal. Silakan coba lagi.');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Respons lebih dari 20 detik. Periksa koneksi lalu coba lagi.');
    }
    if (error instanceof SyntaxError) throw new Error('Respons server bukan JSON yang valid.');
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
