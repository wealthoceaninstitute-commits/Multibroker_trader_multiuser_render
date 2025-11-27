import axios from 'axios';
import API_BASE from '../src/lib/apiBase.js';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// 🔥 Automatically inject user token
api.interceptors.request.use(
  (config) => {
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("authToken"); // or woi_token
      if (token) {
        config.headers["X-Auth-Token"] = token;
      }
    }
    return config;
  },
  (error) => Promise.reject(error)
);

export default api;
