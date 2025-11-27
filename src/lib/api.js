// src/lib/api.js
import axios from "axios";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE,
});

// Automatically include token for all API calls
api.interceptors.request.use((config) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  if (token) {
    config.headers["X-Auth-Token"] = token;
  }
  return config;
});
