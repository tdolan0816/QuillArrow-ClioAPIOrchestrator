/**
 * API client for the Clio API Orchestrator backend.
 *
 * Handles JWT token storage and automatic injection into every request.
 * All API calls go through this module so auth is handled in one place.
 */

const API_BASE = '/api';

/**
 * Read JSON from a fetch Response, with clear errors when the body is empty or not JSON
 * (common when the backend is down and Vite's proxy returns an empty 502).
 */
async function readJsonResponse(response) {
  const text = await response.text();
  if (!text.trim()) {
    throw new Error(
      `Empty response from API (HTTP ${response.status}). ` +
        'Is the API server running? For local dev, start the backend on port 8000 (Vite proxies /api there).',
    );
  }
  try {
    return JSON.parse(text);
  } catch {
    const preview = text.length > 160 ? `${text.slice(0, 160)}…` : text;
    throw new Error(`API returned non-JSON (HTTP ${response.status}): ${preview}`);
  }
}

/** Get the stored JWT token */
export function getToken() {
  return localStorage.getItem('token');
}

/** Store the JWT token after login */
export function setToken(token) {
  localStorage.setItem('token', token);
}

/** Clear the token (logout) */
export function clearToken() {
  localStorage.removeItem('token');
}

/**
 * Make an authenticated API request.
 * Automatically adds the Authorization header if a token exists.
 */
async function request(endpoint, options = {}) {
  const token = getToken();
  const headers = { ...options.headers };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new Error('Session expired. Please log in again.');
  }

  const data = await readJsonResponse(response);

  if (!response.ok) {
    throw new Error(data.detail || data.error || `API error ${response.status}`);
  }

  return data;
}

/** GET request */
export const get = (endpoint) => request(endpoint);

/** POST request with JSON body */
export const post = (endpoint, body) =>
  request(endpoint, { method: 'POST', body });

/** POST request with FormData (for file uploads) */
export const postForm = (endpoint, formData) =>
  request(endpoint, { method: 'POST', body: formData });

/** Login and store the JWT token */
export async function login(username, password) {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);

  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    body: formData,
  });

  const data = await readJsonResponse(response);

  if (!response.ok) {
    throw new Error(data.detail || 'Login failed');
  }

  setToken(data.access_token);
  return data;
}
