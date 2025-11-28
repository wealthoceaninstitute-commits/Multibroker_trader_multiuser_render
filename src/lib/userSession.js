"use client";

const STORAGE_KEY = "mb_current_user";

/**
 * Read current user from localStorage.
 * Returns: { username, token? } or null
 */
export function getCurrentUser() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (err) {
    console.error("Failed to read current user from localStorage:", err);
    return null;
  }
}

/**
 * Save current user in localStorage.
 */
export function setCurrentUser(user) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  } catch (err) {
    console.error("Failed to save current user:", err);
  }
}

/**
 * Clear current user.
 */
export function clearCurrentUser() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (err) {
    console.error("Failed to clear current user:", err);
  }
}
