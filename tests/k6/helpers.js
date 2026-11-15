// Helpers for k6 testing of Spec 2 Scraping Pipeline API

import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import { BASE_URL, API_KEY, REQUEST_TIMEOUT } from './config.js';

// Track server failures independently of expected 4xx validation/auth results.
export const http5xxRate = new Rate('http_5xx_rate');

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
  const response = http.get(url, params);
  http5xxRate.add(response.status >= 500);
  return response;
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
  const response = http.post(url, bodyString, params);
  http5xxRate.add(response.status >= 500);
  return response;
}

// Submit a deliberately concurrent batch while preserving per-request headers.
export function httpBatchPost(path, payloads, customKey = API_KEY) {
  const url = `${BASE_URL}${path}`;
  const requests = payloads.map(({ body, headers = {}, tags = {} }) => ({
    method: 'POST',
    url,
    body: JSON.stringify(body),
    params: {
      headers: authHeaders(customKey, headers),
      timeout: REQUEST_TIMEOUT,
      tags,
    },
  }));

  const responses = http.batch(requests);
  responses.forEach((response) => http5xxRate.add(response.status >= 500));
  return responses;
}

// Safe JSON parser
export function safeJson(res) {
  try {
    return JSON.parse(res.body);
  } catch (e) {
    return null;
  }
}
