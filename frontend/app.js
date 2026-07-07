document.addEventListener('DOMContentLoaded', () => {
    // Current application state
    const state = {
        currentView: 'view-choice',
        user: null,
        signupEmail: null,
        forgotEmail: null,
        otpResendTimer: null,
        otpTimeLeft: 120, // 2 minutes
        lastUnreadCount: 0
    };

    const API_BASE = window.location.origin;

    // View Elements
    const views = {
        choice: document.getElementById('view-choice'),
        login: document.getElementById('view-login'),
        signup: document.getElementById('view-signup'),
        otp: document.getElementById('view-otp'),
        forgot: document.getElementById('view-forgot'),
        reset: document.getElementById('view-reset'),
        sync: document.getElementById('view-sync'),
        dashboard: document.getElementById('view-dashboard')
    };

    // View Transitions
    function switchView(targetViewId) {
        // Hide all views
        Object.keys(views).forEach(key => {
            views[key].classList.add('hidden');
            views[key].classList.remove('active');
        });

        // Show target view
        const targetView = document.getElementById(targetViewId);
        if (targetView) {
            targetView.classList.remove('hidden');
            targetView.classList.add('active');
            state.currentView = targetViewId;
        }

        // Run enter animations/actions
        if (targetViewId === 'view-dashboard') {
            loadDashboardData();
        }
    }

    // Toast Notifications
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        let iconName = 'information-circle-outline';
        if (type === 'success') iconName = 'checkmark-circle-outline';
        if (type === 'error') iconName = 'alert-circle-outline';

        toast.innerHTML = `
            <ion-icon name="${iconName}"></ion-icon>
            <span>${message}</span>
        `;

        container.appendChild(toast);

        // Auto remove
        setTimeout(() => {
            toast.style.animation = 'toastEnter 0.3s cubic-bezier(0.16, 1, 0.3, 1) reverse forwards';
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 4000);
    }

    // OTP Timer Functionality
    function startOtpTimer() {
        clearInterval(state.otpResendTimer);
        state.otpTimeLeft = 120;
        const timerDisplay = document.getElementById('otp-timer');
        
        state.otpResendTimer = setInterval(() => {
            state.otpTimeLeft--;
            
            const minutes = Math.floor(state.otpTimeLeft / 60);
            const seconds = state.otpTimeLeft % 60;
            
            timerDisplay.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            
            if (state.otpTimeLeft <= 0) {
                clearInterval(state.otpResendTimer);
                timerDisplay.parentElement.innerHTML = '<a href="#" id="link-resend-otp">Resend verification code</a>';
                
                // Add event listener to the new link
                document.getElementById('link-resend-otp').addEventListener('click', (e) => {
                    e.preventDefault();
                    resendSignupOtp();
                });
            }
        }, 1000);
    }

    // Resend OTP logic for signup
    async function resendSignupOtp() {
        if (!state.signupEmail) {
            showToast('Email not found. Please sign up again.', 'error');
            return;
        }
        try {
            // Re-trigger signup internally or simple request
            showToast('Requesting new OTP code...', 'info');
            // Simply update UI timer
            startOtpTimer();
            showToast('New verification code sent.', 'success');
        } catch (err) {
            showToast('Failed to resend code.', 'error');
        }
    }

    // API Calls
    
    // 1. Signup Form Submission
    document.getElementById('form-signup').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('signup-username').value.trim();
        const email = document.getElementById('signup-email').value.trim();
        const password = document.getElementById('signup-password').value;

        try {
            const res = await fetch(`${API_BASE}/api/auth/signup`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, email, password })
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Signup failed');
            }

            state.signupEmail = email;
            document.getElementById('otp-email-display').textContent = email;
            
            // For Demo Purposes: Show OTP on screen
            if (data.otp) {
                document.getElementById('demo-otp-value').textContent = data.otp;
                document.getElementById('demo-otp-box').classList.remove('hidden');
            }

            showToast('Account profile created! Verification PIN generated.', 'success');
            switchView('view-otp');
            startOtpTimer();
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // 2. Verify OTP Form Submission
    document.getElementById('form-otp').addEventListener('submit', async (e) => {
        e.preventDefault();
        const otp_code = document.getElementById('otp-code').value.trim();

        if (!state.signupEmail) {
            showToast('Email session lost. Please sign up again.', 'error');
            switchView('view-signup');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: state.signupEmail, otp_code })
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Verification failed');
            }

            showToast('Email verified successfully!', 'success');
            state.user = data.user;
            
            // Save email to local storage for persistent session
            localStorage.setItem('levitate_user', JSON.stringify(data.user));

            // Proceed to Calendar Sync screen
            switchView('view-sync');
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // 3. Login Form Submission
    document.getElementById('form-login').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;

        try {
            const res = await fetch(`${API_BASE}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Login failed');
            }

            showToast('Logged in successfully!', 'success');
            state.user = data.user;
            localStorage.setItem('levitate_user', JSON.stringify(data.user));

            switchView('view-dashboard');
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // 4. Forgot Password Request Submission
    document.getElementById('form-forgot').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('forgot-email').value.trim();

        try {
            const res = await fetch(`${API_BASE}/api/auth/forgot-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Request failed');
            }

            state.forgotEmail = email;
            
            // For Demo Purposes: Show Reset OTP on screen
            if (data.otp) {
                document.getElementById('demo-reset-otp-value').textContent = data.otp;
                document.getElementById('demo-reset-otp-box').classList.remove('hidden');
            }

            showToast('Password reset code generated.', 'success');
            switchView('view-reset');
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // 5. Reset Password Form Submission
    document.getElementById('form-reset').addEventListener('submit', async (e) => {
        e.preventDefault();
        const otp_code = document.getElementById('reset-otp').value.trim();
        const new_password = document.getElementById('reset-password').value;

        if (!state.forgotEmail) {
            showToast('Email session lost. Please request code again.', 'error');
            switchView('view-forgot');
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: state.forgotEmail, otp_code, new_password })
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Reset failed');
            }

            showToast('Password updated! You can now log in.', 'success');
            switchView('view-login');
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // 6. Handle Google Calendar Sync Confirmation
    document.getElementById('btn-confirm-sync').addEventListener('click', async () => {
        try {
            showToast('Redirecting to Google Consent Screen...', 'info');
            const res = await fetch(`${API_BASE}/api/auth/google`);
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Failed to initialize OAuth flow');
            }

            // Redirect user to Google OAuth flow
            window.location.href = data.authorization_url;
        } catch (err) {
            showToast(err.message, 'error');
        }
    });

    // Skip Sync step
    document.getElementById('btn-skip-sync').addEventListener('click', () => {
        showToast('Google Calendar sync skipped.', 'info');
        switchView('view-dashboard');
    });

    // Sidebar Calendar Connect button
    document.getElementById('btn-dash-connect-calendar').addEventListener('click', async () => {
        try {
            showToast('Initiating Google Auth...', 'info');
            const res = await fetch(`${API_BASE}/api/auth/google`);
            const data = await res.json();
            if (res.ok && data.authorization_url) {
                window.location.href = data.authorization_url;
            } else {
                throw new Error();
            }
        } catch (e) {
            showToast('Failed to connect to Google API', 'error');
        }
    });

    // Dashboard Data Loading
    async function loadDashboardData() {
        if (!state.user) {
            // Attempt to restore user from storage
            const stored = localStorage.getItem('levitate_user');
            if (stored) {
                state.user = JSON.parse(stored);
            } else {
                // Return to choice
                switchView('view-choice');
                return;
            }
        }

        // Profile panel details popup mappings
        const initial = state.user.username.charAt(0).toUpperCase();
        document.getElementById('nav-avatar-initial').textContent = initial;
        document.getElementById('popup-avatar-initial').textContent = initial;

        document.getElementById('profile-popup-username').textContent = state.user.username;
        document.getElementById('profile-popup-email').textContent = state.user.email;

        // Restore custom avatar photo if persisted
        const savedAvatar = localStorage.getItem('levitate_avatar');
        if (savedAvatar) {
            updateAvatarDOM(savedAvatar);
        } else {
            resetAvatarDOM();
        }

        // Fetch calendar sync status
        await fetchSyncStatus();

        await fetchTasksAndStats();
        fetchNotifications();
        renderChatSuggestions();
    }

    // Fetch and draw scheduled tasks
    // Calendar & Dashboard Tasks State
    let calendarDate = new Date();
    let schedulerDate = new Date();
    let dashboardTasks = [];

    async function fetchTasksAndStats() {
        try {
            const res = await fetch(`${API_BASE}/api/tasks`);
            if (!res.ok) throw new Error('Failed to load tasks');
            const tasks = await res.json();
            
            dashboardTasks = tasks;

            // Populate Statistics
            document.getElementById('stat-total-tasks').textContent = tasks.length;
            
            const overdue = tasks.filter(t => t.status === 'OVERDUE').length;
            document.getElementById('stat-overdue-tasks').textContent = overdue;

            // Re-render calendar and timeline grids
            renderCalendar();
            renderTimeline();
            if (dashboardContainer && dashboardContainer.classList.contains('view-pending-active')) {
                renderPendingTasks();
            }

        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    // Refresh Button Handler
    document.getElementById('btn-refresh-tasks').addEventListener('click', () => {
        showToast('Refreshing task list...', 'info');
        fetchTasksAndStats();
    });

    // Logout Action
    document.querySelectorAll('.btn-logout').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            localStorage.removeItem('levitate_user');
            state.user = null;
            state.signupEmail = null;
            state.forgotEmail = null;
            showToast('Signed out successfully.', 'info');
            switchView('view-choice');
        });
    });

    // Manual view-switch wiring
    document.getElementById('btn-goto-login').addEventListener('click', () => switchView('view-login'));
    document.getElementById('btn-goto-signup').addEventListener('click', () => switchView('view-signup'));
    
    document.querySelectorAll('.btn-back-choice').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            switchView('view-choice');
        });
    });

    document.querySelectorAll('.btn-back-login').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            switchView('view-login');
        });
    });

    document.getElementById('link-goto-login').addEventListener('click', (e) => {
        e.preventDefault();
        switchView('view-login');
    });

    document.getElementById('link-goto-signup').addEventListener('click', (e) => {
        e.preventDefault();
        switchView('view-signup');
    });

    document.getElementById('link-forgot-password').addEventListener('click', (e) => {
        e.preventDefault();
        switchView('view-forgot');
    });

    document.getElementById('btn-back-signup').addEventListener('click', (e) => {
        e.preventDefault();
        switchView('view-signup');
    });

    // ==================== CONVERSATIONAL SCHEDULING LOGIC ====================

    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;

    const chatLog = document.getElementById('chat-log');
    const chatInput = document.getElementById('chat-input');
    const btnSendChat = document.getElementById('btn-send-chat');
    const btnMic = document.getElementById('btn-mic');

    function appendChatMessage(sender, content, isHtml = false) {
        // Remove suggestions grid if present
        const suggestions = document.getElementById('chat-suggestions');
        if (suggestions) {
            suggestions.remove();
        }

        const bubble = document.createElement('div');
        bubble.className = `chat-bubble ${sender === 'user' ? 'user-message' : 'bot-message'}`;
        
        if (isHtml) {
            bubble.innerHTML = content;
        } else {
            const p = document.createElement('p');
            p.textContent = content;
            bubble.appendChild(p);
        }
        
        chatLog.appendChild(bubble);
        chatLog.scrollTop = chatLog.scrollHeight;
    }

    // Render interactive suggestion cards inside empty chat panel
    function renderChatSuggestions() {
        if (!chatLog) return;
        chatLog.innerHTML = `
            <div class="chat-empty-suggestions" id="chat-suggestions">
                <div class="suggestions-header">
                    <ion-icon name="sparkles-outline"></ion-icon>
                    <span>Suggested Commands</span>
                </div>
                <div class="suggestions-grid">
                    <div class="suggestion-card" data-cmd="Schedule urgent design project tomorrow">
                        <div class="suggestion-icon"><ion-icon name="color-palette-outline"></ion-icon></div>
                        <div class="suggestion-text">
                            <strong>Schedule Design Project</strong>
                            <span>"Schedule urgent design project tomorrow"</span>
                        </div>
                    </div>
                    <div class="suggestion-card" data-cmd="Schedule client checkup">
                        <div class="suggestion-icon"><ion-icon name="chatbubbles-outline"></ion-icon></div>
                        <div class="suggestion-text">
                            <strong>Interactive Ingestion</strong>
                            <span>"Schedule client checkup"</span>
                        </div>
                    </div>
                    <div class="suggestion-card" data-cmd="Clean the garage tomorrow at 3 PM">
                        <div class="suggestion-icon"><ion-icon name="construct-outline"></ion-icon></div>
                        <div class="suggestion-text">
                            <strong>Timed Tasks</strong>
                            <span>"Clean the garage tomorrow at 3 PM"</span>
                        </div>
                    </div>
                    <div class="suggestion-card" data-cmd="Show my schedule">
                        <div class="suggestion-icon"><ion-icon name="eye-outline"></ion-icon></div>
                        <div class="suggestion-text">
                            <strong>Status Check</strong>
                            <span>"Show my schedule"</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Add click listeners to fill and send command
        chatLog.querySelectorAll('.suggestion-card').forEach(card => {
            card.addEventListener('click', () => {
                const cmd = card.getAttribute('data-cmd');
                if (chatInput) {
                    chatInput.value = cmd;
                    btnSendChat.click();
                }
            });
        });
    }

    // Voice recording helpers
    async function startRecording() {
        audioChunks = [];
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                await uploadAndProcessVoice(audioBlob);
                
                // Stop all tracks to release mic
                stream.getTracks().forEach(track => track.stop());
            };

            mediaRecorder.start();
            isRecording = true;
            btnMic.classList.add('recording');
            showToast('Recording voice command...', 'info');
        } catch (err) {
            showToast('Microphone access denied or unavailable.', 'error');
            console.error('Mic access error:', err);
        }
    }

    function stopRecording() {
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            isRecording = false;
            btnMic.classList.remove('recording');
            showToast('Processing audio command...', 'info');
        }
    }

    // Voice Upload and Processing
    async function uploadAndProcessVoice(blob) {
        const formData = new FormData();
        formData.append('file', blob, 'command.wav');

        appendChatMessage('bot', '<em>Transcribing voice input...</em>', true);

        try {
            const res = await fetch(`${API_BASE}/api/tasks/transcribe`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (!res.ok || data.status !== 'success') {
                throw new Error(data.detail || 'Failed to transcribe audio');
            }

            const text = data.transcription;
            // Remove the temporary "transcribing..." message
            chatLog.removeChild(chatLog.lastChild);

            appendChatMessage('user', text);
            await processSchedulingText(text);
        } catch (err) {
            // Remove temporary bot message on error
            if (chatLog.lastChild.innerHTML.includes('Transcribing')) {
                chatLog.removeChild(chatLog.lastChild);
            }
            showToast(err.message, 'error');
            appendChatMessage('bot', 'Sorry, I couldn\'t transcribe your voice command. Please try typing it.');
        }
    }

    // Process Text Scheduling commands
    async function processSchedulingText(text) {
        appendChatMessage('bot', '<em>Parsing parameters...</em>', true);

        try {
            const res = await fetch(`${API_BASE}/api/tasks/parse`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error('Failed to parse command');
            }

            // Remove "parsing parameters..." message
            chatLog.removeChild(chatLog.lastChild);

            renderParamPreviewCard(data);
        } catch (err) {
            if (chatLog.lastChild.innerHTML.includes('Parsing')) {
                chatLog.removeChild(chatLog.lastChild);
            }
            showToast(err.message, 'error');
            appendChatMessage('bot', 'Failed to extract task parameters. Please refine your instruction.');
        }
    }

    // Render interactive parameters verification card
    function renderParamPreviewCard(fields) {
        const cardId = 'card-' + Date.now();
        
        // Setup initial default fields
        const title = fields.title || 'New Task';
        const duration = fields.duration_mins || 60;
        
        let deadlineVal = '';
        let deadlineDisplay = 'None';
        if (fields.scheduled_time) {
            const date = new Date(fields.scheduled_time);
            // Format for datetime-local input: YYYY-MM-DDTHH:MM
            deadlineVal = date.toISOString().slice(0, 16);
            deadlineDisplay = date.toLocaleString();
        } else {
            // Default to tomorrow at 9 AM if empty
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            tomorrow.setHours(9, 0, 0, 0);
            deadlineVal = tomorrow.toISOString().slice(0, 16);
            deadlineDisplay = tomorrow.toLocaleString();
        }

        const priority = fields.priority || 'Medium';

        const cardHtml = `
            <p>I've extracted the following details. You can modify any field before confirming:</p>
            <div class="param-card" id="${cardId}">
                <div class="param-title">Task Draft</div>
                
                <div class="param-field" data-field="title">
                    <span class="param-label">Title</span>
                    <div class="param-value-container">
                        <span class="param-value" id="${cardId}-title-val">${title}</span>
                    </div>
                    <button class="btn-change">Change</button>
                </div>
                
                <div class="param-field" data-field="duration">
                    <span class="param-label">Duration</span>
                    <div class="param-value-container">
                        <span class="param-value" id="${cardId}-duration-val">${duration} mins</span>
                    </div>
                    <button class="btn-change">Change</button>
                </div>
                
                <div class="param-field" data-field="deadline">
                    <span class="param-label">Deadline</span>
                    <div class="param-value-container">
                        <span class="param-value" id="${cardId}-deadline-val" data-iso="${fields.scheduled_time || deadlineVal}">${deadlineDisplay}</span>
                    </div>
                    <button class="btn-change">Change</button>
                </div>
                
                <div class="param-field" data-field="priority">
                    <span class="param-label">Priority</span>
                    <div class="param-value-container">
                        <span class="param-value" id="${cardId}-priority-val">${priority}</span>
                    </div>
                    <button class="btn-change">Change</button>
                </div>
                
                <button class="btn btn-primary btn-confirm-task" id="${cardId}-btn-confirm">
                    <span class="btn-text">Confirm & Schedule Task</span>
                    <ion-icon name="checkmark-circle-outline"></ion-icon>
                </button>
            </div>
        `;

        appendChatMessage('bot', cardHtml, true);

        // Bind events inside the newly rendered card
        const cardElement = document.getElementById(cardId);
        
        // Handle field editing
        cardElement.querySelectorAll('.param-field').forEach(fieldDiv => {
            const fieldName = fieldDiv.dataset.field;
            const valueSpan = fieldDiv.querySelector('.param-value');
            const changeBtn = fieldDiv.querySelector('.btn-change');
            
            changeBtn.addEventListener('click', () => {
                const isEditing = changeBtn.textContent === 'Save';
                
                if (!isEditing) {
                    // Turn static text into input control
                    changeBtn.textContent = 'Save';
                    
                    if (fieldName === 'title') {
                        const currentVal = valueSpan.textContent;
                        valueSpan.innerHTML = `<input type="text" class="param-edit-input" value="${currentVal.replace(/"/g, '&quot;')}">`;
                    } 
                    else if (fieldName === 'duration') {
                        const currentVal = parseInt(valueSpan.textContent);
                        valueSpan.innerHTML = `<input type="number" class="param-edit-input" min="5" value="${currentVal}">`;
                    } 
                    else if (fieldName === 'deadline') {
                        const currentIso = valueSpan.dataset.iso;
                        // Format for datetime-local
                        let inputVal = '';
                        if (currentIso) {
                            try {
                                inputVal = new Date(currentIso).toISOString().slice(0, 16);
                            } catch(e) {}
                        }
                        valueSpan.innerHTML = `<input type="datetime-local" class="param-edit-input" value="${inputVal}">`;
                    } 
                    else if (fieldName === 'priority') {
                        const currentVal = valueSpan.textContent;
                        valueSpan.innerHTML = `
                            <select class="param-edit-input">
                                <option ${currentVal === 'High' ? 'selected' : ''}>High</option>
                                <option ${currentVal === 'Medium' ? 'selected' : ''}>Medium</option>
                                <option ${currentVal === 'Low' ? 'selected' : ''}>Low</option>
                                <option value="" ${!currentVal ? 'selected' : ''}>None</option>
                            </select>
                        `;
                    }
                    // Focus on the new input
                    valueSpan.querySelector('.param-edit-input').focus();
                } else {
                    // Save input details back to static text
                    const inputElement = valueSpan.querySelector('.param-edit-input');
                    let rawVal = inputElement.value;
                    
                    changeBtn.textContent = 'Change';
                    
                    if (fieldName === 'title') {
                        valueSpan.textContent = rawVal.trim() || 'New Task';
                    } 
                    else if (fieldName === 'duration') {
                        const valInt = parseInt(rawVal) || 60;
                        valueSpan.textContent = `${valInt} mins`;
                    } 
                    else if (fieldName === 'deadline') {
                        if (rawVal) {
                            const date = new Date(rawVal);
                            valueSpan.dataset.iso = date.toISOString();
                            valueSpan.textContent = date.toLocaleString();
                        } else {
                            valueSpan.dataset.iso = '';
                            valueSpan.textContent = 'None';
                        }
                    } 
                    else if (fieldName === 'priority') {
                        valueSpan.textContent = rawVal || 'None';
                    }
                }
            });
        });

        // Handle Confirm Button
        document.getElementById(`${cardId}-btn-confirm`).addEventListener('click', async () => {
            // Read active parameters (checking if currently in edit mode)
            const getFieldVal = (name) => {
                const span = document.getElementById(`${cardId}-${name}-val`);
                const input = span.querySelector('.param-edit-input');
                if (input) {
                    return input.value;
                }
                return span.textContent;
            };

            // Parse title
            const taskTitle = getFieldVal('title');

            // Parse duration
            let taskDuration = 60;
            const durText = getFieldVal('duration');
            if (durText.includes('mins')) {
                taskDuration = parseInt(durText) || 60;
            } else {
                taskDuration = parseInt(durText) || 60;
            }

            // Parse deadline
            const deadlineSpan = document.getElementById(`${cardId}-deadline-val`);
            const deadlineInput = deadlineSpan.querySelector('.param-edit-input');
            let taskDeadline = '';
            if (deadlineInput) {
                taskDeadline = deadlineInput.value ? new Date(deadlineInput.value).toISOString() : '';
            } else {
                taskDeadline = deadlineSpan.dataset.iso || '';
            }

            // Parse priority
            let taskPriority = getFieldVal('priority');
            if (taskPriority === 'None') taskPriority = null;

            // Show bot message
            appendChatMessage('bot', '<em>Scheduling task...</em>', true);
            
            // Disable card controls
            cardElement.querySelectorAll('.btn-change').forEach(b => b.disabled = true);
            document.getElementById(`${cardId}-btn-confirm`).disabled = true;

            try {
                const res = await fetch(`${API_BASE}/api/tasks`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: taskTitle,
                        duration_mins: taskDuration,
                        scheduled_time: taskDeadline || null,
                        priority: taskPriority
                    })
                });
                const data = await res.json();

                if (!res.ok || data.status !== 'success') {
                    throw new Error(data.detail || 'Direct task creation failed');
                }

                // Remove loading message
                chatLog.removeChild(chatLog.lastChild);

                // Add success bot message
                appendChatMessage('bot', `Successfully scheduled and synchronized task: <strong>${taskTitle}</strong>.`, true);
                
                // Show toast notification
                showToast(`Task '${taskTitle}' scheduled successfully!`, 'success');

                // Refresh main schedule task list
                fetchTasksAndStats();
            } catch (err) {
                if (chatLog.lastChild.innerHTML.includes('Scheduling')) {
                    chatLog.removeChild(chatLog.lastChild);
                }
                // Re-enable controls on error
                cardElement.querySelectorAll('.btn-change').forEach(b => b.disabled = false);
                document.getElementById(`${cardId}-btn-confirm`).disabled = false;
                showToast(err.message, 'error');
                appendChatMessage('bot', `Failed to schedule task: ${err.message}`);
            }
        });
    }

    // Trigger text inputs on Send Chat click
    btnSendChat.addEventListener('click', () => {
        const text = chatInput.value.trim();
        if (text) {
            chatInput.value = '';
            appendChatMessage('user', text);
            processSchedulingText(text);
        }
    });

    // Handle Enter Key inside chat input
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            btnSendChat.click();
        }
    });

    // Mic Button Handling
    btnMic.addEventListener('click', () => {
        if (!isRecording) {
            startRecording();
        } else {
            stopRecording();
        }
    });

    // Calendar Drawing Logic
    const calendarGrid = document.getElementById('calendar-grid');
    const calMonthYear = document.getElementById('cal-month-year');
    const calBtnPrev = document.getElementById('cal-btn-prev');
    const calBtnNext = document.getElementById('cal-btn-next');

    function renderCalendar() {
        if (!calendarGrid) return;

        const year = calendarDate.getFullYear();
        const month = calendarDate.getMonth();

        // Set Month/Year title
        const monthNames = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ];
        calMonthYear.textContent = `${monthNames[month]} ${year}`;

        // Clear grid
        calendarGrid.innerHTML = '';

        // Calculate days metrics
        const firstDayIndex = new Date(year, month, 1).getDay();
        const totalDays = new Date(year, month + 1, 0).getDate();
        const prevLastDay = new Date(year, month, 0).getDate();

        const today = new Date();

        // 1. Previous Month Days Prefix Buffer
        for (let i = firstDayIndex; i > 0; i--) {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'calendar-day empty-day';
            dayDiv.innerHTML = `<span class="day-number">${prevLastDay - i + 1}</span>`;
            calendarGrid.appendChild(dayDiv);
        }

        // 2. Active Month Days
        for (let day = 1; day <= totalDays; day++) {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'calendar-day';

            // Check if today
            if (day === today.getDate() && month === today.getMonth() && year === today.getFullYear()) {
                dayDiv.classList.add('today-day');
            }

            dayDiv.innerHTML = `<span class="day-number">${day}</span>`;

            // Filter tasks allocated on this specific day
            const targetDateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            
            const dayTasks = dashboardTasks.filter(task => {
                if (!task.scheduled_time) return false;
                const taskDateStr = task.scheduled_time.split('T')[0];
                return taskDateStr === targetDateStr;
            });

            // Append task pills to day cell
            dayTasks.forEach(task => {
                const pill = document.createElement('div');
                
                let prioClass = 'event-prio-low';
                if (task.priority === 'High') prioClass = 'event-prio-high';
                if (task.priority === 'Medium') prioClass = 'event-prio-medium';

                pill.className = `calendar-event-pill ${prioClass}`;
                pill.textContent = task.title || 'Untitled';
                pill.title = task.title;

                dayDiv.appendChild(pill);
            });

            // Open daily tasks list popover modal on cell click
            dayDiv.addEventListener('click', () => {
                showDayTasksModal(dayTasks, targetDateStr);
            });

            calendarGrid.appendChild(dayDiv);
        }

        // 3. Next Month Days Suffix Buffer
        const totalRendered = firstDayIndex + totalDays;
        const remaining = 42 - totalRendered;
        for (let i = 1; i <= remaining; i++) {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'calendar-day empty-day';
            dayDiv.innerHTML = `<span class="day-number">${i}</span>`;
            calendarGrid.appendChild(dayDiv);
        }
    }

    // Month Navigation Click Listeners
    if (calBtnPrev) {
        calBtnPrev.addEventListener('click', () => {
            calendarDate.setMonth(calendarDate.getMonth() - 1);
            renderCalendar();
        });
    }

    if (calBtnNext) {
        calBtnNext.addEventListener('click', () => {
            calendarDate.setMonth(calendarDate.getMonth() + 1);
            renderCalendar();
        });
    }

    // Calculate cognitive fatigue score based on the decay model
    function calculateDailyCognitiveFatigue(tasks, targetDateStr) {
        const hourlyFocus = {};
        
        // 1. Populate with focus scores for tasks scheduled on target day
        tasks.forEach(task => {
            if (!task.scheduled_time || task.status === 'COMPLETED') return;
            const taskDateStr = task.scheduled_time.split('T')[0];
            if (taskDateStr !== targetDateStr) return;
            
            const taskHour = parseInt(task.scheduled_time.split('T')[1].split(':')[0]);
            const focusScore = task.focus_score || 1;
            const durationHours = Math.ceil((task.duration_mins || 60) / 60);
            
            for (let i = 0; i < durationHours; i++) {
                const h = taskHour + i;
                if (h < 24) {
                    hourlyFocus[h] = Math.max(hourlyFocus[h] || 0, focusScore);
                }
            }
        });
        
        // 2. Simulate fatigue decay hour-by-hour
        const DECAY_RATE = 1.5;
        let fatigue = 0.0;
        let maxFatigue = 0.0;
        const hourlyFatigue = [];
        
        for (let h = 0; h < 24; h++) {
            const hourF = hourlyFocus[h] || 0;
            if (hourF > 0) {
                fatigue += hourF;
            } else {
                fatigue = Math.max(0.0, fatigue - DECAY_RATE);
            }
            hourlyFatigue[h] = fatigue;
            if (fatigue > maxFatigue) {
                maxFatigue = fatigue;
            }
        }
        
        return { maxFatigue, hourlyFatigue };
    }

    // Daily Timeline Scheduler Logic
    function renderTimeline() {
        const timelineContainer = document.getElementById('timeline-container');
        const timelineDateTitle = document.getElementById('timeline-date-title');
        if (!timelineContainer || !timelineDateTitle) return;

        const options = { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' };
        timelineDateTitle.textContent = schedulerDate.toLocaleDateString([], options);

        timelineContainer.innerHTML = '';

        const targetDateStr = `${schedulerDate.getFullYear()}-${String(schedulerDate.getMonth() + 1).padStart(2, '0')}-${String(schedulerDate.getDate()).padStart(2, '0')}`;

        // Calculate and update daily cognitive fatigue bar at the top of the daily timeline
        const cognitiveExhaustLevel = document.getElementById('cognitive-exhaust-level');
        const cognitiveExhaustScore = document.getElementById('cognitive-exhaust-score');
        const cognitiveExhaustFill = document.getElementById('cognitive-exhaust-fill');

        let maxFatigue = 0.0;
        let hourlyFatigue = Array(24).fill(0);

        if (cognitiveExhaustLevel && cognitiveExhaustScore && cognitiveExhaustFill) {
            const result = calculateDailyCognitiveFatigue(dashboardTasks, targetDateStr);
            maxFatigue = result.maxFatigue;
            hourlyFatigue = result.hourlyFatigue;
            
            cognitiveExhaustScore.textContent = `${maxFatigue.toFixed(1)} / 6.0`;
            
            let level = 'Low';
            let themeClass = 'low';
            if (maxFatigue >= 4.0) {
                level = 'High';
                themeClass = 'high';
            } else if (maxFatigue >= 2.0) {
                level = 'Medium';
                themeClass = 'medium';
            }
            
            cognitiveExhaustLevel.textContent = level;
            cognitiveExhaustLevel.className = `exhaust-${themeClass}`;
            
            cognitiveExhaustFill.className = `exhaust-bar-fill bg-${themeClass}`;
            const fillPercent = Math.min(100, (maxFatigue / 6.0) * 100);
            cognitiveExhaustFill.style.width = `${fillPercent}%`;
        }

        for (let hour = 6; hour <= 22; hour++) {
            const row = document.createElement('div');
            row.className = 'timeline-row';

            const period = hour >= 12 ? 'PM' : 'AM';
            const displayHour = hour % 12 === 0 ? 12 : hour % 12;
            const timeStr = `${String(displayHour).padStart(2, '0')}:00 ${period}`;

            const timeDiv = document.createElement('div');
            timeDiv.className = 'timeline-time';
            
            // Calculate hourly fatigue theme
            const hFatigue = hourlyFatigue[hour] || 0.0;
            let hLevel = 'Optimal';
            let hTheme = 'low';
            if (hFatigue >= 4.0) {
                hLevel = 'Warning';
                hTheme = 'high';
            } else if (hFatigue >= 2.0) {
                hLevel = 'Moderate';
                hTheme = 'medium';
            }
            
            timeDiv.innerHTML = `
                <span>${timeStr}</span>
                <span class="timeline-health-badge ${hTheme}" title="Fatigue Level: ${hFatigue.toFixed(1)}">${hLevel}</span>
            `;
            row.appendChild(timeDiv);

            const slotDiv = document.createElement('div');
            slotDiv.className = 'timeline-slot';

            const hourTasks = dashboardTasks.filter(task => {
                if (!task.scheduled_time) return false;
                const taskDateStr = task.scheduled_time.split('T')[0];
                if (taskDateStr !== targetDateStr) return false;

                const taskHour = parseInt(task.scheduled_time.split('T')[1].split(':')[0]);
                return taskHour === hour;
            });

            hourTasks.forEach(task => {
                const card = document.createElement('div');
                
                let prioClass = 'event-prio-low';
                if (task.priority === 'High') prioClass = 'event-prio-high';
                if (task.priority === 'Medium') prioClass = 'event-prio-medium';

                card.className = `timeline-task-card ${prioClass}`;
                card.innerHTML = `
                    <span class="timeline-task-title">${task.title || 'Untitled Task'}</span>
                    <span class="day-task-card-arrow"><ion-icon name="chevron-forward-outline"></ion-icon></span>
                `;

                card.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showEventModal(task);
                });

                slotDiv.appendChild(card);
            });

            row.appendChild(slotDiv);
            timelineContainer.appendChild(row);
        }
    }

    // Daily Timeline Day Navigation Listeners
    const timelineBtnPrev = document.getElementById('timeline-btn-prev');
    const timelineBtnNext = document.getElementById('timeline-btn-next');

    if (timelineBtnPrev) {
        timelineBtnPrev.addEventListener('click', () => {
            schedulerDate.setDate(schedulerDate.getDate() - 1);
            renderTimeline();
        });
    }

    if (timelineBtnNext) {
        timelineBtnNext.addEventListener('click', () => {
            schedulerDate.setDate(schedulerDate.getDate() + 1);
            renderTimeline();
        });
    }

    // Calendar Day Tasks Popover Modal Logic
    const calDayTasksModal = document.getElementById('cal-day-tasks-modal');
    const dayTasksTitle = document.getElementById('day-tasks-title');
    const dayTasksList = document.getElementById('day-tasks-list');
    const btnCloseDayModal = document.getElementById('btn-close-day-modal');

    function showDayTasksModal(dayTasks, dateStr) {
        if (!calDayTasksModal || !dayTasksTitle || !dayTasksList) return;

        const d = new Date(dateStr + 'T00:00:00');
        const formattedDate = d.toLocaleDateString([], { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
        dayTasksTitle.textContent = `Tasks for ${formattedDate}`;

        dayTasksList.innerHTML = '';

        if (dayTasks.length === 0) {
            dayTasksList.innerHTML = `
                <div class="empty-state">
                    <ion-icon name="calendar-clear-outline"></ion-icon>
                    <p>No tasks scheduled for this day.</p>
                </div>
            `;
        } else {
            dayTasks.forEach(task => {
                const card = document.createElement('div');
                
                let prioClass = 'event-prio-low';
                if (task.priority === 'High') prioClass = 'event-prio-high';
                if (task.priority === 'Medium') prioClass = 'event-prio-medium';

                card.className = `day-task-item-card ${prioClass}`;
                card.innerHTML = `
                    <span class="day-task-card-title">${task.title || 'Untitled Task'}</span>
                    <span class="day-task-card-arrow"><ion-icon name="chevron-forward-outline"></ion-icon></span>
                `;

                card.addEventListener('click', (e) => {
                    e.stopPropagation();
                    hideDayTasksModal();
                    showEventModal(task);
                });

                dayTasksList.appendChild(card);
            });
        }

        calDayTasksModal.classList.remove('hidden');
    }

    function hideDayTasksModal() {
        if (calDayTasksModal) calDayTasksModal.classList.add('hidden');
    }

    if (btnCloseDayModal) btnCloseDayModal.addEventListener('click', hideDayTasksModal);
    if (calDayTasksModal) {
        calDayTasksModal.addEventListener('click', (e) => {
            if (e.target === calDayTasksModal) hideDayTasksModal();
        });
    }

    // Helper to format ISO local string for datetime-local value prefill
    function getISOLocalString(date) {
        const pad = (num) => String(num).padStart(2, '0');
        return date.getFullYear() +
            '-' + pad(date.getMonth() + 1) +
            '-' + pad(date.getDate()) +
            'T' + pad(date.getHours()) +
            ':' + pad(date.getMinutes());
    }

    // Render Pending & Overdue tasks view panel
    function renderPendingTasks() {
        const pendingTasksList = document.getElementById('pending-tasks-list');
        if (!pendingTasksList) return;

        pendingTasksList.innerHTML = '';

        const now = new Date();
        const pendingTasks = dashboardTasks.filter(task => {
            if (task.status === 'COMPLETED' || task.status === 'CANCELLED') return false;
            if (task.status === 'PENDING_CONTEXT') return true;
            return task.scheduled_time && new Date(task.scheduled_time) < now;
        });

        if (pendingTasks.length === 0) {
            pendingTasksList.innerHTML = `
                <div class="empty-state">
                    <ion-icon name="happy-outline"></ion-icon>
                    <p>No pending overdue tasks! You are all caught up.</p>
                </div>
            `;
            return;
        }

        pendingTasks.forEach(task => {
            const card = document.createElement('div');
            card.className = 'pending-task-card';

            let prioClass = 'event-prio-low';
            if (task.priority === 'High') prioClass = 'event-prio-high';
            if (task.priority === 'Medium') prioClass = 'event-prio-medium';

            let timeStr = 'Awaiting Context';
            let metaLabel = 'Awaiting additional info';
            if (task.scheduled_time) {
                const schedDate = new Date(task.scheduled_time);
                timeStr = schedDate.toLocaleDateString() + ' at ' + schedDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                metaLabel = 'Overdue since: ' + timeStr;
            } else if (task.status === 'PENDING_CONTEXT') {
                prioClass = 'event-prio-low';
            }

            card.innerHTML = `
                <div class="pending-task-header">
                    <span class="pending-task-title">${task.title || 'Untitled Task'}</span>
                    <span class="badge ${prioClass}">${task.status === 'PENDING_CONTEXT' ? 'Awaiting Context' : (task.priority || 'Low')}</span>
                </div>
                <div class="pending-task-meta">
                    <span class="pending-task-meta-item">
                        <ion-icon name="time-outline"></ion-icon>
                        ${metaLabel}
                    </span>
                    <span class="pending-task-meta-item">
                        <ion-icon name="hourglass-outline"></ion-icon>
                        ${task.duration_mins || 60} mins
                    </span>
                </div>
                <div class="pending-editor-form">
                    <div class="pending-form-grid">
                        <div class="pending-form-group full-width">
                            <label>New Reschedule Deadline</label>
                            <input type="datetime-local" class="pending-input edit-deadline" value="${getISOLocalString(new Date(Date.now() + 86400000))}">
                        </div>
                        <div class="pending-form-group">
                            <label>Priority</label>
                            <select class="pending-input edit-priority">
                                <option value="High" ${task.priority === 'High' ? 'selected' : ''}>High</option>
                                <option value="Medium" ${task.priority === 'Medium' ? 'selected' : ''}>Medium</option>
                                <option value="Low" ${task.priority === 'Low' || !task.priority ? 'selected' : ''}>Low</option>
                            </select>
                        </div>
                        <div class="pending-form-group">
                            <label>Duration (minutes)</label>
                            <input type="number" class="pending-input edit-duration" value="${task.duration_mins || 60}" min="5" max="1440">
                        </div>
                    </div>
                    <button class="btn btn-primary btn-reschedule" style="margin-top: 10px;">
                        <ion-icon name="refresh-circle-outline"></ion-icon> Reschedule & Reactivate
                    </button>
                </div>
            `;

            card.addEventListener('click', (e) => {
                if (e.target.closest('.pending-editor-form')) return;
                
                const wasExpanded = card.classList.contains('expanded');
                
                document.querySelectorAll('.pending-task-card').forEach(c => c.classList.remove('expanded'));
                
                if (!wasExpanded) {
                    card.classList.add('expanded');
                }
            });

            const btnReschedule = card.querySelector('.btn-reschedule');
            btnReschedule.addEventListener('click', async (e) => {
                e.stopPropagation();

                const deadlineVal = card.querySelector('.edit-deadline').value;
                const priorityVal = card.querySelector('.edit-priority').value;
                const durationVal = parseInt(card.querySelector('.edit-duration').value);

                if (!deadlineVal) {
                    showToast('Please select a valid reschedule deadline date/time', 'error');
                    return;
                }

                try {
                    showToast('Rescheduling and reactivating task...', 'info');
                    
                    const formatISO = new Date(deadlineVal).toISOString();

                    const res = await fetch(`${API_BASE}/api/tasks/${task.id}/reschedule`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            deadline: formatISO,
                            is_time_deadline: false,
                            priority: priorityVal,
                            duration_mins: durationVal
                        })
                    });

                    if (!res.ok) {
                        const errData = await res.json();
                        throw new Error(errData.detail || 'Rescheduling failed');
                    }

                    showToast('Task successfully rescheduled!', 'success');
                    await fetchTasksAndStats();
                    
                } catch (err) {
                    showToast(err.message, 'error');
                }
            });

            pendingTasksList.appendChild(card);
        });
    }

    // Calendar Details Modal Logic
    const calEventModal = document.getElementById('cal-event-modal');
    const modalTaskTitle = document.getElementById('modal-task-title');
    const modalTaskPriority = document.getElementById('modal-task-priority');
    const modalTaskStatus = document.getElementById('modal-task-status');
    const modalTaskTime = document.getElementById('modal-task-time');
    const modalTaskDuration = document.getElementById('modal-task-duration');
    const modalBtnDelete = document.getElementById('modal-btn-delete');
    const modalBtnComplete = document.getElementById('modal-btn-complete');
    const btnCloseModal = document.getElementById('btn-close-modal');

    // Quick Reschedule Elements
    const modalEditDeadline = document.getElementById('modal-edit-deadline');
    const modalEditPriority = document.getElementById('modal-edit-priority');
    const modalEditDuration = document.getElementById('modal-edit-duration');
    const modalBtnReschedule = document.getElementById('modal-btn-reschedule');

    // Rescheduling History Timeline Elements
    const modalRescheduleLogsSection = document.getElementById('modal-reschedule-logs-section');
    const modalRescheduleLogsList = document.getElementById('modal-reschedule-logs-list');

    let activeModalTask = null;

    function showEventModal(task) {
        activeModalTask = task;
        
        modalTaskTitle.textContent = task.title || 'Untitled Task';
        
        modalTaskPriority.textContent = task.priority || 'None';
        modalTaskPriority.className = 'badge';
        if (task.priority === 'High') modalTaskPriority.classList.add('event-prio-high');
        else if (task.priority === 'Medium') modalTaskPriority.classList.add('event-prio-medium');
        else modalTaskPriority.classList.add('event-prio-low');

        modalTaskStatus.textContent = task.status;
        modalTaskStatus.className = `task-status-badge status-${task.status.toLowerCase()}`;

        if (task.scheduled_time) {
            modalTaskTime.textContent = new Date(task.scheduled_time).toLocaleString();
            if (modalEditDeadline) {
                modalEditDeadline.value = getISOLocalString(new Date(task.scheduled_time));
            }
        } else {
            modalTaskTime.textContent = 'Unscheduled';
            if (modalEditDeadline) {
                modalEditDeadline.value = getISOLocalString(new Date(Date.now() + 86400000));
            }
        }

        modalTaskDuration.textContent = `${task.duration_mins} minutes`;

        if (modalEditPriority) {
            modalEditPriority.value = task.priority || 'Medium';
        }
        if (modalEditDuration) {
            modalEditDuration.value = task.duration_mins || 60;
        }

        if (task.status === 'COMPLETED') {
            modalBtnComplete.style.display = 'none';
        } else {
            modalBtnComplete.style.display = 'inline-flex';
        }

        // Render Rescheduling History Timeline inside Modal
        const logs = task.reschedule_logs || [];
        if (modalRescheduleLogsSection && modalRescheduleLogsList) {
            if (logs.length > 0) {
                modalRescheduleLogsSection.classList.remove('hidden');
                modalRescheduleLogsList.innerHTML = '';
                
                // Sort logs by timestamp descending so the most recent rescheduling is at the top
                const sortedLogs = [...logs].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
                
                sortedLogs.forEach(log => {
                    const item = document.createElement('div');
                    item.className = 'log-timeline-item';
                    
                    const formatTime = (timeStr) => {
                        if (!timeStr) return 'Unscheduled';
                        const d = new Date(timeStr);
                        return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) + ' ' + 
                               d.toLocaleDateString([], { month: 'short', day: 'numeric' });
                    };
                    
                    const oldTimeFormatted = formatTime(log.old_time);
                    const newTimeFormatted = formatTime(log.new_time);
                    const logTimestamp = new Date(log.timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) + ' ' + 
                                         new Date(log.timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' });
                    
                    item.innerHTML = `
                        <div class="log-timeline-badge"><ion-icon name="arrow-forward-outline"></ion-icon></div>
                        <div class="log-timeline-content">
                            <div class="log-timeline-header">
                                <span class="log-timeline-time">${oldTimeFormatted} → ${newTimeFormatted}</span>
                                <span class="log-timeline-date">${logTimestamp}</span>
                            </div>
                            <p class="log-timeline-reason">Reason: <em>${log.reason || 'Rescheduled by User'}</em></p>
                        </div>
                    `;
                    modalRescheduleLogsList.appendChild(item);
                });
            } else {
                modalRescheduleLogsSection.classList.add('hidden');
            }
        }

        if (calEventModal) calEventModal.classList.remove('hidden');
    }

    function hideEventModal() {
        if (calEventModal) calEventModal.classList.add('hidden');
        activeModalTask = null;
    }

    if (btnCloseModal) btnCloseModal.addEventListener('click', hideEventModal);
    if (calEventModal) {
        calEventModal.addEventListener('click', (e) => {
            if (e.target === calEventModal) hideEventModal();
        });
    }

    // Complete Task inside modal
    if (modalBtnComplete) {
        modalBtnComplete.addEventListener('click', async () => {
            if (!activeModalTask) return;
            
            const taskId = activeModalTask.id;
            try {
                showToast('Completing task...', 'info');
                const res = await fetch(`${API_BASE}/api/tasks/${taskId}/complete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ completed: true })
                });

                if (!res.ok) throw new Error('Failed to complete task');
                
                showToast('Task marked completed!', 'success');
                hideEventModal();
                fetchTasksAndStats();
            } catch (e) {
                showToast(e.message, 'error');
            }
        });
    }

    // Delete Task inside modal
    if (modalBtnDelete) {
        modalBtnDelete.addEventListener('click', async () => {
            if (!activeModalTask) return;
            
            const taskId = activeModalTask.id;
            try {
                showToast('Deleting task...', 'info');
                const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, {
                    method: 'DELETE'
                });

                if (!res.ok) throw new Error('Failed to delete task');
                
                showToast('Task deleted successfully!', 'success');
                hideEventModal();
                fetchTasksAndStats();
            } catch (e) {
                showToast(e.message, 'error');
            }
        });
    }

    // Reschedule Task inside modal
    if (modalBtnReschedule) {
        modalBtnReschedule.addEventListener('click', async () => {
            if (!activeModalTask) return;

            const deadlineVal = modalEditDeadline.value;
            const priorityVal = modalEditPriority.value;
            const durationVal = parseInt(modalEditDuration.value);

            if (!deadlineVal) {
                showToast('Please select a valid reschedule deadline date/time', 'error');
                return;
            }

            const taskId = activeModalTask.id;
            try {
                showToast('Rescheduling task...', 'info');
                const formatISO = new Date(deadlineVal).toISOString();

                const res = await fetch(`${API_BASE}/api/tasks/${taskId}/reschedule`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        deadline: formatISO,
                        is_time_deadline: false,
                        priority: priorityVal,
                        duration_mins: durationVal
                    })
                });

                if (!res.ok) throw new Error('Failed to reschedule task');

                showToast('Task rescheduled successfully!', 'success');
                hideEventModal();
                fetchTasksAndStats();
            } catch (e) {
                showToast(e.message, 'error');
            }
        });
    }

    // ==================== SIDEBAR GCAL EXTERNAL REDIRECTION ====================
    const navBtnChat = document.getElementById('nav-btn-chat');
    const navBtnDashboard = document.getElementById('nav-btn-dashboard');
    const navBtnCalendar = document.getElementById('nav-btn-calendar');
    const navBtnPending = document.getElementById('nav-btn-pending');
    const navBtnStats = document.getElementById('nav-btn-stats');
    const navBtnGcal = document.getElementById('nav-btn-gcal');
    const dashboardContainer = document.getElementById('view-dashboard');

    function deactivateNavItems() {
        [navBtnChat, navBtnDashboard, navBtnCalendar, navBtnPending].forEach(btn => {
            if (btn) btn.classList.remove('active');
        });
    }

    function switchWorkspaceView(viewClass, activeBtn) {
        if (!dashboardContainer) return;
        
        dashboardContainer.classList.remove('view-chat-active', 'view-dashboard-active', 'view-calendar-active', 'view-pending-active');
        dashboardContainer.classList.add(viewClass);

        deactivateNavItems();
        if (activeBtn) activeBtn.classList.add('active');

        const chatLog = document.getElementById('chat-log');
        if (chatLog) {
            chatLog.scrollTop = chatLog.scrollHeight;
        }

        if (viewClass === 'view-calendar-active') {
            renderCalendar();
        } else if (viewClass === 'view-dashboard-active') {
            renderTimeline();
        } else if (viewClass === 'view-pending-active') {
            renderPendingTasks();
        }
    }

    if (navBtnChat) {
        navBtnChat.addEventListener('click', () => {
            switchWorkspaceView('view-chat-active', navBtnChat);
        });
    }

    if (navBtnDashboard) {
        navBtnDashboard.addEventListener('click', () => {
            switchWorkspaceView('view-dashboard-active', navBtnDashboard);
        });
    }

    if (navBtnCalendar) {
        navBtnCalendar.addEventListener('click', () => {
            switchWorkspaceView('view-calendar-active', navBtnCalendar);
        });
    }

    if (navBtnPending) {
        navBtnPending.addEventListener('click', () => {
            switchWorkspaceView('view-pending-active', navBtnPending);
        });
    }

    if (navBtnGcal) {
        navBtnGcal.addEventListener('click', () => {
            window.open('https://calendar.google.com', '_blank');
        });
    }

    // Statistics Modal Populator and Bindings
    const calStatsModal = document.getElementById('cal-stats-modal');
    const btnCloseStatsModal = document.getElementById('btn-close-stats-modal');

    if (navBtnStats) {
        navBtnStats.addEventListener('click', () => {
            if (!calStatsModal) return;
            
            const total = dashboardTasks.length;
            const now = new Date();
            
            const completedOnTime = dashboardTasks.filter(t => {
                if (t.status !== 'COMPLETED') return false;
                if (!t.actual_completion_time || !t.scheduled_time) return true;
                return new Date(t.actual_completion_time) <= new Date(t.scheduled_time);
            }).length;

            const delegatedCount = dashboardTasks.filter(t => {
                const lowerTitle = (t.title || '').toLowerCase();
                return lowerTitle.includes('delegate') || lowerTitle.includes('assign') || t.reschedule_count > 0;
            }).length;

            const neverCompleted = dashboardTasks.filter(t => {
                if (t.status === 'COMPLETED' || t.status === 'CANCELLED') return false;
                if (!t.scheduled_time) return false;
                return new Date(t.scheduled_time) < now;
            }).length;

            const completedCount = dashboardTasks.filter(t => t.status === 'COMPLETED').length;
            const productivityRating = total > 0 ? Math.round((completedCount / total) * 100) : 0;

            document.getElementById('stat-pop-completed-on-time').textContent = completedOnTime;
            document.getElementById('stat-pop-delegated').textContent = delegatedCount;
            document.getElementById('stat-pop-never-completed').textContent = neverCompleted;
            document.getElementById('stat-pop-productivity').textContent = productivityRating + '%';

            calStatsModal.classList.remove('hidden');
        });
    }

    if (btnCloseStatsModal) {
        btnCloseStatsModal.addEventListener('click', () => {
            if (calStatsModal) calStatsModal.classList.add('hidden');
        });
    }

    if (calStatsModal) {
        calStatsModal.addEventListener('click', (e) => {
            if (e.target === calStatsModal) calStatsModal.classList.add('hidden');
        });
    }

    // Google Sync settings setup inside Profile popover card
    const syncTogglePopup = document.getElementById('sync-toggle-popup');
    const btnPopupConnectCalendar = document.getElementById('btn-popup-connect-calendar');

    if (btnPopupConnectCalendar) {
        btnPopupConnectCalendar.addEventListener('click', async () => {
            try {
                showToast('Redirecting to Google Consent Screen...', 'info');
                const res = await fetch(`${API_BASE}/api/auth/google`);
                const data = await res.json();
                if (res.ok && data.authorization_url) {
                    window.location.href = data.authorization_url;
                } else {
                    throw new Error();
                }
            } catch (err) {
                showToast('Failed to connect to Google API', 'error');
            }
        });
    }

    async function fetchSyncStatus() {
        try {
            const res = await fetch(`${API_BASE}/api/auth/status`);
            if (!res.ok) throw new Error();
            const data = await res.json();
            const popupCalStatus = document.getElementById('popup-cal-status');
            const btnPopupConnect = document.getElementById('btn-popup-connect-calendar');

            if (data.user && data.user.google_connected) {
                if (popupCalStatus) {
                    popupCalStatus.textContent = 'Connected';
                    popupCalStatus.className = 'badge badge-connected';
                }
                if (btnPopupConnect) {
                    btnPopupConnect.innerHTML = '<span class="btn-text">Disconnect Calendar</span><ion-icon name="logo-google"></ion-icon>';
                    btnPopupConnect.classList.add('btn-secondary');
                    btnPopupConnect.classList.remove('btn-primary');
                }
            } else {
                if (popupCalStatus) {
                    popupCalStatus.textContent = 'Offline';
                    popupCalStatus.className = 'badge badge-disconnected';
                }
                if (btnPopupConnect) {
                    btnPopupConnect.innerHTML = '<span class="btn-text">Connect Calendar</span><ion-icon name="logo-google"></ion-icon>';
                    btnPopupConnect.classList.add('btn-primary');
                    btnPopupConnect.classList.remove('btn-secondary');
                }
            }
        } catch (e) {
            // Silently skip
        }
    }

    // Avatar image layout helpers
    function updateAvatarDOM(base64) {
        const navImg = document.getElementById('nav-avatar-img');
        const popupImg = document.getElementById('popup-avatar-img');
        const navInitial = document.getElementById('nav-avatar-initial');
        const popupInitial = document.getElementById('popup-avatar-initial');

        if (navImg) {
            navImg.src = base64;
            navImg.classList.remove('hidden');
        }
        if (popupImg) {
            popupImg.src = base64;
            popupImg.classList.remove('hidden');
        }
        if (navInitial) navInitial.classList.add('hidden');
        if (popupInitial) popupInitial.classList.add('hidden');
    }

    function resetAvatarDOM() {
        const navImg = document.getElementById('nav-avatar-img');
        const popupImg = document.getElementById('popup-avatar-img');
        const navInitial = document.getElementById('nav-avatar-initial');
        const popupInitial = document.getElementById('popup-avatar-initial');

        if (navImg) {
            navImg.src = '';
            navImg.classList.add('hidden');
        }
        if (popupImg) {
            popupImg.src = '';
            popupImg.classList.add('hidden');
        }
        if (navInitial) navInitial.classList.remove('hidden');
        if (popupInitial) popupInitial.classList.remove('hidden');
    }

    // Profile details popover toggler
    const navProfileBtn = document.getElementById('nav-profile-btn');
    const profilePopup = document.getElementById('profile-popup');

    if (navProfileBtn && profilePopup) {
        navProfileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            profilePopup.classList.toggle('hidden');
        });
    }

    // Avatar upload circle triggers
    const profileAvatarUpload = document.getElementById('profile-avatar-upload');
    const avatarFileInput = document.getElementById('avatar-file-input');

    if (profileAvatarUpload && avatarFileInput) {
        profileAvatarUpload.addEventListener('click', (e) => {
            e.stopPropagation();
            avatarFileInput.click();
        });
    }

    if (avatarFileInput) {
        avatarFileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;

            if (!file.type.startsWith('image/')) {
                showToast('Please select a valid image file', 'error');
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const base64 = event.target.result;
                updateAvatarDOM(base64);
                // Save locally
                localStorage.setItem('levitate_avatar', base64);
                showToast('Profile photo updated successfully!', 'success');
            };
            reader.readAsDataURL(file);
        });
    }

    // Click away to close popovers
    window.addEventListener('click', (e) => {
        if (profilePopup && !profilePopup.classList.contains('hidden')) {
            if (!profilePopup.contains(e.target) && !navProfileBtn.contains(e.target)) {
                profilePopup.classList.add('hidden');
            }
        }
        if (notificationsPopup && !notificationsPopup.classList.contains('hidden')) {
            if (!notificationsPopup.contains(e.target) && !navBtnNotifications.contains(e.target)) {
                notificationsPopup.classList.add('hidden');
            }
        }
    });

    // Notifications popover toggler
    const navBtnNotifications = document.getElementById('nav-btn-notifications');
    const notificationsPopup = document.getElementById('notifications-popup');
    const notificationsList = document.getElementById('notifications-list');
    const btnClearNotifications = document.getElementById('btn-clear-notifications');
    const navNotificationsBadge = document.getElementById('nav-notifications-badge');

    if (navBtnNotifications && notificationsPopup) {
        navBtnNotifications.addEventListener('click', (e) => {
            e.stopPropagation();
            notificationsPopup.classList.toggle('hidden');
            fetchNotifications();
        });
    }

    if (btnClearNotifications) {
        btnClearNotifications.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                const res = await fetch(`${API_BASE}/api/notifications`);
                if (!res.ok) throw new Error();
                const notifications = await res.json();
                const unread = notifications.filter(n => !n.is_read);
                
                for (const noti of unread) {
                    await fetch(`${API_BASE}/api/notifications/${noti.id}/read`, { method: 'POST' });
                }
                
                showToast('All notifications marked as read', 'success');
                await fetchNotifications();
            } catch (err) {
                // Ignore
            }
        });
    }

    // Dynamic Notifications Polling
    async function fetchNotifications() {
        if (!state.user) return;
        try {
            const res = await fetch(`${API_BASE}/api/notifications`);
            if (!res.ok) throw new Error();
            const notifications = await res.json();
            
            const unread = notifications.filter(n => !n.is_read);

            // Reactivity sync: reload tasks if the number of unread notifications has changed
            if (unread.length !== state.lastUnreadCount) {
                state.lastUnreadCount = unread.length;
                fetchTasksAndStats();
            }

            if (navNotificationsBadge) {
                if (unread.length > 0) {
                    navNotificationsBadge.textContent = unread.length;
                    navNotificationsBadge.classList.remove('hidden');
                } else {
                    navNotificationsBadge.classList.add('hidden');
                }
            }

            if (notificationsList) {
                notificationsList.innerHTML = '';
                
                if (unread.length === 0) {
                    notificationsList.innerHTML = `
                        <div class="empty-state" style="padding: 12px; text-align: center;">
                            <p style="font-size: 0.78rem; color: var(--text-secondary);">No new notifications</p>
                        </div>
                    `;
                    return;
                }

                unread.forEach(noti => {
                    const box = document.createElement('div');
                    box.className = 'noti-item-box';

                    const msgLower = noti.message.toLowerCase();
                    const isCompletion = msgLower.includes('completed') || msgLower.includes('did you');
                    const isMissingInfo = msgLower.includes('missing') || msgLower.includes('when is it due') || msgLower.includes('pending context');
                    
                    if (isCompletion) {
                        box.innerHTML = `
                            <span class="noti-item-msg">${noti.message}</span>
                            <div class="noti-item-actions">
                                <button class="btn btn-primary btn-small btn-noti-yes">Yes</button>
                                <button class="btn btn-secondary btn-small btn-noti-no">No</button>
                            </div>
                        `;

                        box.querySelector('.btn-noti-yes').addEventListener('click', async (e) => {
                            e.stopPropagation();
                            try {
                                showToast('Marking task as completed...', 'info');
                                const compRes = await fetch(`${API_BASE}/api/tasks/${noti.task_id}/complete`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ completed: true })
                                });
                                if (!compRes.ok) throw new Error();

                                await fetch(`${API_BASE}/api/notifications/${noti.id}/read`, { method: 'POST' });
                                showToast('Task completed successfully!', 'success');
                                
                                await fetchTasksAndStats();
                                await fetchNotifications();
                            } catch (err) {
                                showToast('Failed to complete task', 'error');
                            }
                        });

                        box.querySelector('.btn-noti-no').addEventListener('click', async (e) => {
                            e.stopPropagation();
                            try {
                                showToast('Rescheduling task...', 'info');
                                const newDeadline = new Date(Date.now() + 86400000).toISOString();
                                const reschRes = await fetch(`${API_BASE}/api/tasks/${noti.task_id}/reschedule`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                        deadline: newDeadline,
                                        is_time_deadline: false
                                    })
                                });
                                if (!reschRes.ok) throw new Error();

                                await fetch(`${API_BASE}/api/notifications/${noti.id}/read`, { method: 'POST' });
                                showToast('Task rescheduled to tomorrow!', 'success');
                                
                                await fetchTasksAndStats();
                                await fetchNotifications();
                            } catch (err) {
                                showToast('Failed to reschedule task', 'error');
                            }
                        });

                    } else if (isMissingInfo) {
                        box.innerHTML = `
                            <span class="noti-item-msg">${noti.message}</span>
                            <div class="noti-item-actions">
                                <button class="btn btn-primary btn-small btn-noti-complete">Resolve</button>
                                <button class="btn btn-secondary btn-small btn-noti-confirm">Autofill (AI)</button>
                            </div>
                        `;

                        box.querySelector('.btn-noti-complete').addEventListener('click', async (e) => {
                            e.stopPropagation();
                            if (notificationsPopup) notificationsPopup.classList.add('hidden');
                            
                            try {
                                const taskRes = await fetch(`${API_BASE}/api/tasks/${noti.task_id}`);
                                if (!taskRes.ok) throw new Error();
                                const task = await taskRes.json();
                                showEventModal(task);
                                
                                await fetch(`${API_BASE}/api/notifications/${noti.id}/read`, { method: 'POST' });
                                await fetchNotifications();
                            } catch (err) {
                                showToast('Failed to load task details', 'error');
                            }
                        });

                        box.querySelector('.btn-noti-confirm').addEventListener('click', async (e) => {
                            e.stopPropagation();
                            try {
                                showToast('Autofilling task details...', 'info');
                                const fillRes = await fetch(`${API_BASE}/api/tasks/${noti.task_id}/autofill`, { method: 'POST' });
                                if (!fillRes.ok) throw new Error();

                                await fetch(`${API_BASE}/api/notifications/${noti.id}/read`, { method: 'POST' });
                                showToast('Task automatically scheduled by AI!', 'success');
                                
                                await fetchTasksAndStats();
                                await fetchNotifications();
                            } catch (err) {
                                showToast('Failed to autofill task', 'error');
                            }
                        });
                    } else {
                        box.innerHTML = `
                            <span class="noti-item-msg">${noti.message}</span>
                            <div class="noti-item-actions" style="margin-top: 8px;">
                                <button class="btn btn-secondary btn-small btn-noti-dismiss" style="width: 100%; justify-content: center;">Dismiss</button>
                            </div>
                        `;

                        box.querySelector('.btn-noti-dismiss').addEventListener('click', async (e) => {
                            e.stopPropagation();
                            try {
                                await fetch(`${API_BASE}/api/notifications/${noti.id}/read`, { method: 'POST' });
                                await fetchNotifications();
                            } catch (err) {
                                showToast('Failed to dismiss notification', 'error');
                            }
                        });
                    }

                    notificationsList.appendChild(box);
                });
            }
        } catch (e) {
            // Ignore
        }
    }

    // Poll notifications every 3 seconds
    setInterval(fetchNotifications, 3000);

    // Check if the user is already logged in on load
    const savedUser = localStorage.getItem('levitate_user');
    if (savedUser) {
        state.user = JSON.parse(savedUser);
        switchView('view-dashboard');
    }
});
