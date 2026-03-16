// Authentication Service for PaperIgnition Web App


class AuthService {
    constructor() {
        this.currentUser = null;
        this.loadUserFromStorage();
    }

    // Check if user is logged in
    isLoggedIn() {
        return !!this.currentUser && !!this.getToken();
    }

    // Get current user
    getCurrentUser() {
        return this.currentUser;
    }

    // Get auth token
    getToken() {
        return localStorage.getItem('token');
    }

    // Set current user
    setUser(user) {
        this.currentUser = user;
        localStorage.setItem('userInfo', JSON.stringify(user));
        
        // Dispatch custom event for UI updates
        window.dispatchEvent(new CustomEvent('authStateChanged', {
            detail: { isLoggedIn: true, user }
        }));
    }

    // Load user from localStorage
    loadUserFromStorage() {
        const token = this.getToken();
        const userInfo = localStorage.getItem('userInfo');
        
        if (token && userInfo) {
            try {
                this.currentUser = JSON.parse(userInfo);
            } catch (error) {
                console.error('Error parsing user info:', error);
                this.logout();
            }
        }
    }

    // Login with email and password
    async login(email, password) {
        try {
            const response = await fetch('/api/auth/login-email', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json' 
                },
                body: JSON.stringify({ email, password })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                // Store token and user info
                localStorage.setItem('token', data.access_token);
                this.setUser(data.user_info);


                return {
                    success: true,
                    needsSetup: data.needs_interest_setup
                };
            } else {
                return {
                    success: false,
                    error: data.detail || 'Login failed'
                };
            }
            
        } catch (error) {
            console.error('Login error:', error);
            return {
                success: false,
                error: 'Network error. Please try again.'
            };
        }
    }

    // Register new user
    async register(email, password, username) {
        try {
            console.log('Register called with:', { email, username });

            // Validation
            if (!email || !password || !username) {
                return {
                    success: false,
                    error: 'All fields are required'
                };
            }

            if (!/\S+@\S+\.\S+/.test(email)) {
                return {
                    success: false,
                    error: 'Please enter a valid email address'
                };
            }

            if (password.length < 6) {
                return {
                    success: false,
                    error: 'Password must be at least 6 characters'
                };
            }

            console.log('Making API call to register...');
            const response = await fetch('/api/auth/register-email', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password, username })
            });

            console.log('API response status:', response.status);
            const data = await response.json();
            console.log('API response data:', data);

            if (response.ok) {
                // Backend now returns EmailLoginResponse: { access_token, user_info, needs_interest_setup }
                // Store token and user info for auto-login
                localStorage.setItem('token', data.access_token);
                this.setUser(data.user_info);

                return {
                    success: true,
                    needsSetup: data.needs_interest_setup
                };
            } else {
                return {
                    success: false,
                    error: data.detail || 'Registration failed'
                };
            }
            
        } catch (error) {
            console.error('Registration error:', error);
            return {
                success: false,
                error: 'Network error. Please try again.'
            };
        }
    }

    // Logout user
    logout() {
        this.currentUser = null;
        localStorage.removeItem('token');
        localStorage.removeItem('userInfo');
        localStorage.removeItem('userEmail');
        
        // Dispatch custom event for UI updates
        window.dispatchEvent(new CustomEvent('authStateChanged', {
            detail: { isLoggedIn: false, user: null }
        }));
    }
}

// Create global instance
window.AuthService = new AuthService();

// Initialize authentication state on page load
document.addEventListener('DOMContentLoaded', () => {
    // Update UI based on current auth state
    updateAuthUI();
    
    // Listen for auth state changes
    window.addEventListener('authStateChanged', updateAuthUI);
});

function updateAuthUI() {
    const isLoggedIn = window.AuthService.isLoggedIn();
    const currentUser = window.AuthService.getCurrentUser();
    
    // Update navigation
    const profileLink = document.querySelector('a[href="#profile"]');
    if (profileLink) {
        if (isLoggedIn) {
            profileLink.textContent = currentUser?.username || 'Profile';
            profileLink.href = 'profile.html';
        } else {
            profileLink.textContent = 'Login';
            profileLink.href = 'login.html';
        }
    }
    
    // Add logout link if logged in
    const nav = document.querySelector('.nav');
    if (nav && isLoggedIn) {
        let logoutLink = document.getElementById('logoutLink');
        if (!logoutLink) {
            logoutLink = document.createElement('a');
            logoutLink.id = 'logoutLink';
            logoutLink.href = '#';
            logoutLink.textContent = 'Logout';
            logoutLink.style.color = 'var(--text-muted)';
            logoutLink.addEventListener('click', (e) => {
                e.preventDefault();
                handleLogout();
            });
            nav.appendChild(logoutLink);
        }
    }
}

function handleLogout() {
    if (confirm('Are you sure you want to logout?')) {
        window.AuthService.logout();
        window.location.href = 'index.html';
    }
}

// Export for ES modules
export default window.AuthService;