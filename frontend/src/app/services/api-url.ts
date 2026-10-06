export function irisApiBase(): string {
  const configured = (window as any).IRIS_API_URL;
  if (configured) return String(configured).replace(/\/+$/, '');
  // En desarrollo Angular usa la API local separada en el puerto 8000.
  if (location.port === '4200' || location.port === '4201') {
    return `${location.protocol}//${location.hostname}:8000`;
  }
  return `${location.origin}/api`;
}
