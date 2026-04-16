/**
 * Authentication context for the React app.
 *
 * Provides login/logout functions and current user state to all components.
 * Wraps the entire app so any component can check if the user is logged in.
 */

import { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, getToken, clearToken, get } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (token) {
      get('/auth/me')
        .then(setUser)
        .catch(() => {
          // Do not clear the token: transient failures (backend down, empty proxy body) would
          // wipe a valid session. Invalid sessions are cleared on HTTP 401 inside request().
          setUser(null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  async function login(username, password) {
    const data = await apiLogin(username, password);
    setUser({ username: data.username, full_name: data.username, role: data.role });
    return data;
  }

  function logout() {
    clearToken();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
