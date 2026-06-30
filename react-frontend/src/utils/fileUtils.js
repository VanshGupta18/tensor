export function base64ToBlob(b64, mimeType = 'application/octet-stream') {
  let binary;
  try {
    binary = atob(b64);
  } catch {
    throw new Error('Invalid PDF data — the server returned malformed content. Try downloading again.');
  }
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mimeType });
}

export function validatePdfFile(file) {
  if (!file) return 'No file selected.';
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    return 'Only PDF files are supported. Please select a .pdf file.';
  }
  if (file.size > 50 * 1024 * 1024) {
    return `File is ${(file.size / 1024 / 1024).toFixed(1)} MB — exceeds the 50 MB limit. Split the PDF and try again.`;
  }
  return null;
}
