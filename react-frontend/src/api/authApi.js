/**
 * api/authApi.js
 *
 * Authentication API calls against the CAP login action.
 */

import { callAction } from './client.js';

/**
 * Authenticate a user.
 * @param {string} username
 * @param {string} password
 * @returns {Promise<{ username: string, role: string }>}
 */
export async function login(username, password) {
  const result = await callAction('login', { username, password });
  return result;
}

/**
 * Register a new user.
 * @param {string} username
 * @param {string} password
 * @returns {Promise<{ username: string, role: string, token: string }>}
 */
export async function register(username, password) {
  const result = await callAction('register', { username, password });
  return result;
}
