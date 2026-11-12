// Helpers for k6 testing of Spec 2 Scraping Pipeline API

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, API_KEY, REQUEST_TIMEOUT } from './config.js';

// Simple RFC 4122 v4 UUID generator for test keys
export function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Build standard request headers
export function authHeaders(customKey = API_KEY, extraHeaders = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };
  if (customKey !== null && customKey !== undefined) {
    headers['X-API-Key'] = customKey;
  }
  return headers;
}

// Wrapper for HTTP GET with standard timeout and headers
export function httpGet(path, customKey = API_KEY, extraParams = {}) {
  const url = `${BASE_URL}${path}`;
  const params = {
    headers: authHeaders(customKey, extraParams.headers || {}),
    timeout: REQUEST_TIMEOUT,
    tags: extraParams.tags || {},
  };
  return http.get(url, params);
}

// Wrapper for HTTP POST with standard timeout and headers
export function httpPost(path, body = {}, customKey = API_KEY, extraParams = {}) {
  const url = `${BASE_URL}${path}`;
  const params = {
    headers: authHeaders(customKey, extraParams.headers || {}),
    timeout: REQUEST_TIMEOUT,
    tags: extraParams.tags || {},
  };
  const bodyString = typeof body === 'string' ? body : JSON.stringify(body);
  return http.post(url, bodyString, params);
}

// Safe JSON parser
export function safeJson(res) {
  try {
    return JSON.parse(res.body);
  } catch (e) {
    return null;
  }
}
