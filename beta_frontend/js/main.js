// Paper data (using the same data from the Taro app)
const samplePapers = [
    {
        id: '1',
        title: 'TigerVector: Bringing High-Performance Vector Search to Graph Databases for Advanced RAG',
        authors: ['Jing Zhang', 'Victor Lee', 'Zhiqi Chen', 'Tianyi Zhang'],
        abstract: 'This paper introduces TigerVector, a novel system that integrates vector search directly into TigerGraph, a distributed graph database. This unified approach aims to overcome the limitations of using separate systems, offering benefits like data consistency, reduced silos, and streamlined hybrid queries for advanced RAG applications.',
        tags: ['Graph Databases', 'Vector Search', 'RAG', 'Performance'],
        submittedDate: '15 May, 2025',
        publishDate: 'May 2025',
        comments: 'Accepted at SIGMOD 2025',
        thumbnail: 'Graph DB'
    },
];

// State management
let allPapers = []; // Store all fetched papers
let currentPapers = []; // Currently displayed papers
let displayedPapersCount = 0; // Track how many papers are currently displayed
const PAPERS_PER_PAGE = 10; // K papers to load at a time (configurable)
let bookmarkedPapers = new Set();
let userFavorites = new Set(); // 新增：存储用户真实的收藏状态
let isLoading = false;
let searchQuery = '';
let hasMorePapers = true; // Track if there are more papers to load

// DOM elements
const papersContainer = document.getElementById('papersContainer');
const loadingIndicator = document.getElementById('loadingIndicator');
const searchInput = document.getElementById('searchInput');

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
    setupEventListeners();
    setupAuthNavigation();
});

async function initializeApp() {
    // Load bookmarks from localStorage
    const savedBookmarks = localStorage.getItem('bookmarkedPapers');
    if (savedBookmarks) {
        bookmarkedPapers = new Set(JSON.parse(savedBookmarks));
    }

    // Check if user is logged in and load their recommendations
    if (window.AuthService && window.AuthService.isLoggedIn()) {
        // 先加载收藏状态，再加载推荐论文，确保收藏状态正确显示
        console.log('Loading user favorites first...');
        await loadUserFavorites();
        console.log('Loading user recommendations...');
        await loadUserRecommendations();
    } else {
        // Load default user recommendations with login suggestion
        await loadDefaultUserRecommendations();
        // Show login suggestion banner AFTER papers are rendered
        if (!window.AuthService || !window.AuthService.isLoggedIn()) {
            showLoginSuggestion();
        }
    }
}

function setupEventListeners() {
    // Search functionality
    searchInput.addEventListener('input', debounce(handleSearch, 300));

    // Infinite scroll
    window.addEventListener('scroll', handleScroll);

    // Theme toggle (if implemented)
    document.addEventListener('keydown', (e) => {
        if (e.key === 'd' && e.ctrlKey) {
            toggleTheme();
        }
    });
}

async function loadUserRecommendations() {
    if (isLoading) return;

    const currentUser = window.AuthService.getCurrentUser();
    if (!currentUser || !currentUser.username) {
        console.error('No user information available');
        showLoginPrompt();
        return;
    }

    isLoading = true;
    showLoading();

    try {
        // Call the backend recommendations API
        const username = currentUser.username;
        const response = await fetch(`/api/digests/recommendations/${encodeURIComponent(username)}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${window.AuthService.getToken()}`
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const papers = await response.json();

        // Transform backend data to match frontend format
        const transformedPapers = papers.map(paper => ({
            id: paper.id,
            title: paper.title,
            authors: paper.authors ? paper.authors.split(', ') : [],
            abstract: paper.abstract || '',
            url: paper.url || '',
            publishDate: paper.submitted,
            thumbnail: 'Paper',
            viewed: paper.viewed || false,
            recommendationDate: paper.recommendation_date,
            blog_liked: paper.blog_liked ?? null, // true = liked, false = disliked, null = no feedback
        }));

        // Deduplicate papers by ID (keep the most recent recommendation)
        const paperMap = new Map();
        transformedPapers.forEach(paper => {
            if (!paperMap.has(paper.id) ||
                new Date(paper.recommendationDate) > new Date(paperMap.get(paper.id).recommendationDate)) {
                paperMap.set(paper.id, paper);
            }
        });
        allPapers = Array.from(paperMap.values());
        currentPapers = []; // Clear displayed papers
        displayedPapersCount = 0;
        hasMorePapers = allPapers.length > 0;

        renderPapers();

        // 批量检查并同步当前论文的收藏状态
        await syncCurrentPapersFavoriteStatus();

    } catch (error) {
        console.error('Error loading recommendations:', error);
        // Fallback to demo papers on error
        showErrorMessage('Failed to load recommendations. Showing sample papers.');
    } finally {
        if (currentPapers.length === 0) {
            console.log('No paper to display, loading default recommendations as fallback');
            await loadDefaultUserRecommendations();
            return; // loadDefaultUserRecommendations handles rendering
        }
        isLoading = false;
        hideLoading();
    }
}

async function loadDefaultUserRecommendations() {
    const defaultUsername = 'BlogBot@gmail.com'; // Default user

    isLoading = true;
    showLoading();

    try {
        const response = await fetch(`/api/digests/recommendations/${encodeURIComponent(defaultUsername)}?limit=10`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const papers = await response.json();

        const transformedPapers = papers.map(paper => ({
            id: paper.id,
            title: paper.title,
            authors: paper.authors ? paper.authors.split(', ') : [],
            abstract: paper.abstract || '',
            url: paper.url || '',
            publishDate: paper.submitted,
            thumbnail: 'Paper',
            viewed: paper.viewed || false,
            recommendationDate: paper.recommendation_date,
            blog_liked: paper.blog_liked ?? null, // true = liked, false = disliked, null = no feedback
        }));

        // Deduplicate papers by ID (keep the most recent recommendation)
        const paperMap = new Map();
        transformedPapers.forEach(paper => {
            if (!paperMap.has(paper.id) ||
                new Date(paper.recommendationDate) > new Date(paperMap.get(paper.id).recommendationDate)) {
                paperMap.set(paper.id, paper);
            }
        });
        allPapers = Array.from(paperMap.values());
        currentPapers = []; // Clear displayed papers
        displayedPapersCount = 0;
        hasMorePapers = allPapers.length > 0;

        renderPapers();

    } catch (error) {
        console.error('Error loading default recommendations:', error);
        showErrorMessage('Failed to load recommendations. Showing sample papers.');
        await loadSamplePapers();
    } finally {
        isLoading = false;
        hideLoading();
    }
}

function showLoginSuggestion() {
    // Check if banner already exists to prevent duplicates
    if (document.getElementById('loginSuggestionBanner')) {
        return;
    }

    // Add a login suggestion banner at the top of papers container
    const banner = document.createElement('div');
    banner.id = 'loginSuggestionBanner';
    banner.style.cssText = `
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 16px 24px;
        margin-bottom: 20px;
        border-radius: 12px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    `;
    banner.innerHTML = `
        <p style="margin: 0; font-size: 16px;">
            📚 You're viewing sample recommendations.
            <a href="login.html" style="color: #ffd700; font-weight: bold; text-decoration: underline;">Login</a>
            or
            <a href="#" id="demoBannerBtn" style="color: #ffd700; font-weight: bold; text-decoration: underline;">Try as Demo User</a>
            to see personalized paper recommendations tailored for you!
        </p>
    `;

    papersContainer.insertBefore(banner, papersContainer.firstChild);

    // Attach demo login handler
    const demoBannerBtn = document.getElementById('demoBannerBtn');
    if (demoBannerBtn) {
        demoBannerBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            demoBannerBtn.textContent = 'Logging in...';
            demoBannerBtn.style.pointerEvents = 'none';
            try {
                const result = await window.AuthService.login('demo@example.com', 'paperignition_demo');
                if (result.success) {
                    window.location.reload();
                } else {
                    demoBannerBtn.textContent = 'Failed - Try again';
                    demoBannerBtn.style.pointerEvents = 'auto';
                }
            } catch (err) {
                demoBannerBtn.textContent = 'Failed - Try again';
                demoBannerBtn.style.pointerEvents = 'auto';
            }
        });
    }
}

function showLoginPrompt() {
    papersContainer.innerHTML = `
        <div class="loading">
            <h2>Welcome to PaperIgnition</h2>
            <p>Please <a href="login.html" style="color: var(--accent-red);">login</a> to see your personalized paper recommendations.</p>
            <br>
            <p>Or view some <button onclick="loadSamplePapers()" style="color: var(--accent-red); background: none; border: none; text-decoration: underline; cursor: pointer;">sample papers</button></p>
        </div>
    `;
}

async function loadSamplePapers() {
    currentPapers = samplePapers;
    renderPapers();

    // 如果用户已登录，批量检查并同步当前论文的收藏状l态
    await syncCurrentPapersFavoriteStatus();
}

async function searchPapersAPI(query) {
    /**
     * Call the backend /find_similar/ API to search for papers
     */
    try {
        const response = await fetch('/find_similar/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                query: query,
                search_strategies: [['tf-idf', 0.8]],  // Format: [[strategy, threshold]]
                top_k: 5,
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log('Search API results:', data);

        // Transform API results to match frontend format
        return (data.results || []).map(result => ({
            id: result.doc_id || result.id,
            title: result.title || result.metadata?.title || 'Untitled',
            authors: result.authors || result.metadata?.authors || [],
            abstract: result.abstract || result.metadata?.abstract || '',
            url: result.url || result.metadata?.url || '',
            publishDate: result.published_date || result.metadata?.published_date || '',
            thumbnail: 'Paper',
            viewed: false,
            recommendationDate: null,
            relevanceScore: result.similarity_score || result.similarity || result.score
        }));
    } catch (error) {
        console.error('Error calling search API:', error);
        throw error;
    }
}

async function loadPapers() {
    // This function is now used primarily for search functionality
    if (!window.AuthService || !window.AuthService.isLoggedIn()) {
        await loadSamplePapers();
        return;
    }

    // For logged-in users: use search API
    if (isLoading) return;

    isLoading = true;
    showLoading();
    console.log('Search input:', searchQuery);

    try {
        if (searchQuery && searchQuery.trim().length > 0) {
            // Call backend search API
            const searchResults = await searchPapersAPI(searchQuery);
            allPapers = searchResults;
            currentPapers = []; // Clear displayed papers
            displayedPapersCount = 0;
            hasMorePapers = allPapers.length > 0;
            console.log(`Search query: "${searchQuery}", Papers found: ${allPapers.length}`);
            if (!allPapers || allPapers.length === 0) {
                console.log('No paper to display');
            }
        } else {
            // No search query - reload original recommendations
            console.log('No search query, reloading user recommendations');
            isLoading = false; // Reset loading to allow loadUserRecommendations to proceed
            await loadUserRecommendations();
            return; // loadUserRecommendations handles rendering and hasMorePapers
        }

        renderPapers();

    } catch (error) {
        console.error('Error in loadPapers:', error);
        showErrorMessage('Search failed');
    } finally {
        isLoading = false;
        hideLoading();
    }
}

function loadMorePapers() {
    const startIdx = displayedPapersCount;
    const endIdx = Math.min(startIdx + PAPERS_PER_PAGE, allPapers.length);

    // Get next batch of papers
    const newPapers = allPapers.slice(startIdx, endIdx);
    currentPapers = [...currentPapers, ...newPapers];
    displayedPapersCount = endIdx;

    // Check if there are more papers to load
    hasMorePapers = displayedPapersCount < allPapers.length;

    return newPapers;
}

function renderPapers(append = false) {
    if (!append) {
        papersContainer.innerHTML = '';
        currentPapers = [];
        displayedPapersCount = 0;
    }

    // Load next batch of papers
    const newPapers = loadMorePapers();

    // Add search results header (only on initial render)
    if (!append && searchQuery && searchQuery.trim().length > 0) {
        const resultsHeader = document.createElement('div');
        resultsHeader.className = 'search-results-header';
        resultsHeader.innerHTML = `
            <p>Showing <strong>${allPapers.length}</strong> results for: "<strong>${searchQuery}</strong>"</p>
        `;
        papersContainer.appendChild(resultsHeader);
    }

    // Render new papers
    newPapers.forEach(paper => {
        const paperElement = createPaperCard(paper);
        papersContainer.appendChild(paperElement);
    });

    // Handle empty states
    if (allPapers.length === 0 && searchQuery && searchQuery.trim().length > 0) {
        const noResultsDiv = document.createElement('div');
        noResultsDiv.className = 'loading';
        noResultsDiv.innerHTML = '<p>No papers found matching your search.</p>';
        papersContainer.appendChild(noResultsDiv);
    } else if (allPapers.length === 0) {
        papersContainer.innerHTML = '<div class="loading"><p>No papers found.</p></div>';
    } else if (!hasMorePapers && currentPapers.length > 0) {
        const noMoreDiv = document.createElement('div');
        noMoreDiv.className = 'no-more-papers';
        noMoreDiv.innerHTML = '<p>No more papers</p>';
        papersContainer.appendChild(noMoreDiv);
    }
}

function createPaperCard(paper) {
    const card = document.createElement('article');
    card.className = 'paper-card';
    card.dataset.paperId = paper.id;

    const viewedIndicator = paper.viewed ? '<span class="viewed-indicator">👁️ Viewed</span>' : '<span class="unviewed-indicator">📄 New</span>';

    // Check if paper is liked/disliked/favorited (from paper data or localStorage)
    // For non-logged-in users, check localStorage first
    const isLoggedIn = window.AuthService && window.AuthService.isLoggedIn();
    let isLiked, isDisliked;

    if (!isLoggedIn) {
        const likeState = localStorage.getItem(`paper_${paper.id}_liked`);
        isLiked = likeState === 'true';
        isDisliked = likeState === 'false';
    } else {
        isLiked = paper.blog_liked === true;
        isDisliked = paper.blog_liked === false;
    }

    const isFavorited = bookmarkedPapers.has(paper.id);

    // Check if we're in search mode (only show favorite button in search)
    const isSearchMode = searchQuery && searchQuery.trim().length > 0;

    // Helper function to create button HTML
    const createButton = (className, isActive, title, svgPath, fillColor = 'none') => `
        <button class="action-btn ${className} ${isActive ? 'active' : ''}" data-action="${className.replace('-btn', '')}" title="${title}">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="${fillColor}" stroke="currentColor" stroke-width="2">
                <path d="${svgPath}"/>
            </svg>
        </button>
    `;

    // SVG paths for buttons
    const likePath = "M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3";
    const dislikePath = "M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17";
    const favoritePath = "M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z";

    // Build action buttons based on mode
    const favoriteBtnHTML = createButton('favorite-btn', isFavorited, isFavorited ? 'Remove from favorites' : 'Add to favorites', favoritePath, isFavorited ? 'currentColor' : 'none');

    let actionButtons = '';
    if (isSearchMode) {
        // Search mode: only show favorite button
        actionButtons = favoriteBtnHTML;
    } else {
        // Explore mode: show all buttons (like, dislike, favorite)
        const likeBtnHTML = createButton('like-btn', isLiked, 'Like this paper', likePath);
        const dislikeBtnHTML = createButton('dislike-btn', isDisliked, 'Dislike this paper', dislikePath);
        actionButtons = likeBtnHTML + dislikeBtnHTML + favoriteBtnHTML;
    }

    card.innerHTML = `
        <div class="paper-content">
            <div class="paper-header">
                <h2 class="paper-title">${paper.title}</h2>
                <div class="paper-header-actions">
                    ${viewedIndicator}
                </div>
            </div>
            <p class="paper-authors">${formatAuthors(paper.authors)}</p>
            <p class="paper-abstract">${paper.abstract}</p>
            <div class="paper-meta">
                <span>Publish Time: ${paper.publishDate ? new Date(paper.publishDate).toLocaleDateString() : "Recent"}</span>
                <span>•</span>
                <span>Recommend Time: ${paper.recommendationDate ? new Date(paper.recommendationDate).toLocaleDateString() : "Recent"}</span>
                ${paper.url ? `<span>•</span><a href="${paper.url}" target="_blank" class="paper-link" onclick="event.stopPropagation()">Paper Link</a>` : ''}
            </div>
        </div>
        <div class="paper-actions">
            ${actionButtons}
        </div>
    `;

    // Add click handler for paper details
    card.addEventListener('click', (e) => {
        // Don't open details if clicking on action buttons
        if (e.target.closest('.action-btn') || e.target.closest('.paper-link')) {
            return;
        }
        showPaperDetail(paper);
    });

    // Add handlers for action buttons
    const likeBtn = card.querySelector('.like-btn');
    const dislikeBtn = card.querySelector('.dislike-btn');
    const favoriteBtn = card.querySelector('.favorite-btn');

    if (likeBtn) {
        likeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            handlePaperAction(paper.id, 'like', likeBtn, dislikeBtn);
        });
    }

    if (dislikeBtn) {
        dislikeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            handlePaperAction(paper.id, 'dislike', dislikeBtn, likeBtn);
        });
    }

    if (favoriteBtn) {
        favoriteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            handleFavoriteAction(paper.id, favoriteBtn);
        });
    }

    return card;
}

// Handle like/dislike actions
async function handlePaperAction(paperId, action, activeBtn, oppositeBtn) {
    const isLoggedIn = window.AuthService && window.AuthService.isLoggedIn();

    if (!isLoggedIn) {
        // For non-logged in users, use localStorage
        const currentLikeState = localStorage.getItem(`paper_${paperId}_liked`);
        const actionValue = action === 'like' ? 'true' : 'false';
        const newState = (currentLikeState === actionValue) ? null : actionValue;

        if (newState === null) {
            localStorage.removeItem(`paper_${paperId}_liked`);
            activeBtn.classList.remove('active');
        } else {
            localStorage.setItem(`paper_${paperId}_liked`, newState);
            activeBtn.classList.add('active');
            oppositeBtn.classList.remove('active');
        }
        return;
    }

    // For logged in users, call backend API
    try {
        const token = window.AuthService.getToken();
        if (!token) {
            throw new Error('No authentication token available');
        }

        const currentUser = window.AuthService.getCurrentUser();
        if (!currentUser || !currentUser.username) {
            throw new Error('Username not available');
        }
        const username = currentUser.username;

        // Determine new blog_liked value: true=like, false=dislike, null=neutral
        const currentState = activeBtn.classList.contains('active');
        const actionValue = action === 'like' ? true : false;
        const blogLiked = currentState ? null : actionValue;

        const response = await fetch(`/api/digests/recommendations/${encodeURIComponent(paperId)}/feedback`, {
            method: 'PUT',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                username: username,
                blog_liked: blogLiked
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }

        // Update UI
        if (blogLiked === null) {
            activeBtn.classList.remove('active');
        } else {
            activeBtn.classList.add('active');
            oppositeBtn.classList.remove('active');
        }

        // Update paper data in currentPapers
        const paper = currentPapers.find(p => p.id === paperId);
        if (paper) {
            paper.blog_liked = blogLiked;
        }

    } catch (error) {
        console.error('Error updating paper feedback:', error);
        showErrorMessage('Failed to update feedback: ' + error.message);
    }
}

// Handle favorite action
async function handleFavoriteAction(paperId, btn) {
    const isLoggedIn = window.AuthService && window.AuthService.isLoggedIn();

    if (!isLoggedIn) {
        // For non-logged in users, use localStorage
        if (bookmarkedPapers.has(paperId)) {
            bookmarkedPapers.delete(paperId);
            btn.classList.remove('active');
            btn.querySelector('svg').setAttribute('fill', 'none');
            btn.setAttribute('title', 'Add to favorites');
        } else {
            bookmarkedPapers.add(paperId);
            btn.classList.add('active');
            btn.querySelector('svg').setAttribute('fill', 'currentColor');
            btn.setAttribute('title', 'Remove from favorites');
        }

        // Save to localStorage
        localStorage.setItem('bookmarkedPapers', JSON.stringify([...bookmarkedPapers]));
        return;
    }

    // For logged in users, use toggleBookmark functionality
    // Find the paper data
    const paper = currentPapers.find(p => p.id === paperId);
    if (!paper) {
        console.error('Paper not found:', paperId);
        return;
    }

    const isCurrentlyFavorited = userFavorites.has(paperId);

    // Show loading state
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.style.opacity = '0.6';
    btn.innerHTML = isCurrentlyFavorited ? 'Removing...' : 'Adding...';

    try {
        const token = window.AuthService.getToken();
        if (!token) {
            throw new Error('No authentication token available');
        }

        if (isCurrentlyFavorited) {
            // Remove from favorites
            const response = await fetch(`/api/favorites/remove/${encodeURIComponent(paperId)}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            // Update local state
            userFavorites.delete(paperId);
            bookmarkedPapers.delete(paperId);

            // Restore original HTML first, then update UI
            btn.innerHTML = originalHtml;
            btn.classList.remove('active');
            const svg = btn.querySelector('svg');
            if (svg) svg.setAttribute('fill', 'none');
            btn.setAttribute('title', 'Add to favorites');

            showSuccessMessage('Removed from favorites');

        } else {
            // Add to favorites
            const authorsStr = Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors;

            const cleanAbstract = (paper.abstract || '')
                .replace(/\r\n/g, '\n')
                .replace(/[""]/g, '"')
                .replace(/['']/g, "'")
                .replace(/…/g, '...')
                .trim();

            const favoriteData = {
                paper_id: String(paper.id).substring(0, 50),
                title: String(paper.title).substring(0, 255),
                authors: String(authorsStr).substring(0, 255),
                abstract: cleanAbstract
            };

            if (paper.url && /^https?:\/\//i.test(String(paper.url))) {
                favoriteData.url = String(paper.url).substring(0, 255);
            }

            const response = await fetch('/api/favorites/add', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(favoriteData)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
            }

            // Update local state
            userFavorites.add(paperId);
            bookmarkedPapers.add(paperId);

            // Restore original HTML first, then update UI
            btn.innerHTML = originalHtml;
            btn.classList.add('active');
            const svg = btn.querySelector('svg');
            if (svg) svg.setAttribute('fill', 'currentColor');
            btn.setAttribute('title', 'Remove from favorites');

            showSuccessMessage('Added to favorites');
        }

    } catch (error) {
        console.error('Error toggling favorite:', error);
        showErrorMessage('Failed to update favorites: ' + error.message);
        // Restore original state
        btn.innerHTML = originalHtml;
    } finally {
        btn.disabled = false;
        btn.style.opacity = '1';
    }
}

async function loadUserFavorites() {
    // Load user's favorites from backend to sync state
    if (!window.AuthService || !window.AuthService.isLoggedIn()) {
        return;
    }

    try {
        const token = window.AuthService.getToken();
        const response = await fetch(`/api/favorites/list`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.ok) {
            const favorites = await response.json(); // 完整的收藏数据

            // Update local favorite state
            userFavorites.clear();
            bookmarkedPapers.clear();

            favorites.forEach(fav => {
                userFavorites.add(fav.paper_id);
                bookmarkedPapers.add(fav.paper_id);
            });

            // Update localStorage
            localStorage.setItem('bookmarkedPapers', JSON.stringify([...bookmarkedPapers]));

            console.log('Favorites loaded:', favorites.length, 'papers');
            console.log('User favorites updated:', [...userFavorites]);

            // Re-render papers to update bookmark states
            if (currentPapers.length > 0) {
                console.log('Re-rendering papers with updated favorite states');
                renderPapers();
            }
        } else {
            console.error('Failed to load favorites:', response.status, response.statusText);
        }
    } catch (error) {
        console.error('Error loading user favorites:', error);
    }
}

async function syncCurrentPapersFavoriteStatus() {
    // 由于批量检查接口在服务器上不存在，这里只是一个占位函数
    // 收藏状态同步主要通过loadUserFavorites()函数完成
    console.log('Sync function called, but using loadUserFavorites for actual sync');
}

function showSuccessMessage(message) {
    // Create temporary success message
    const successDiv = document.createElement('div');
    successDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #10b981;
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        z-index: 1000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideInRight 0.3s ease;
    `;
    successDiv.textContent = message;

    document.body.appendChild(successDiv);

    setTimeout(() => {
        successDiv.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => {
            if (document.body.contains(successDiv)) {
                document.body.removeChild(successDiv);
            }
        }, 300);
    }, 2000);
}

function showErrorMessage(message) {
    // Create temporary error message
    const errorDiv = document.createElement('div');
    errorDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #ef4444;
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        z-index: 1000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideInRight 0.3s ease;
    `;
    errorDiv.textContent = message;

    document.body.appendChild(errorDiv);

    setTimeout(() => {
        errorDiv.style.animation = 'slideOutRight 0.3s ease';
        setTimeout(() => {
            if (document.body.contains(errorDiv)) {
                document.body.removeChild(errorDiv);
            }
        }, 300);
    }, 3000);
}

function handleSearch(event) {
    searchQuery = event.target.value.trim();
    loadPapers(false);
}

function handleScroll() {
    if (isLoading) return;

    // Don't trigger infinite scroll for non-logged-in users (they see default BlogBot papers)
    if (!window.AuthService || !window.AuthService.isLoggedIn()) {
        return;
    }

    // Don't load more if we've reached the end
    if (!hasMorePapers) {
        return;
    }

    const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
    if (scrollTop + clientHeight >= scrollHeight - 5) {
        // Load next K papers
        if (hasMorePapers) {
            renderPapers(true);
        }
    }
}

async function showPaperDetail(paper) {
    if (!paper) return;

    // Mark paper as viewed if user is logged in
    if (window.AuthService && window.AuthService.isLoggedIn()) {
        try {
            const token = window.AuthService.getToken();
            // Call API in background, don't wait for response
            fetch(`/api/digests/${encodeURIComponent(paper.id)}/mark-viewed`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            }).catch(err => console.log('Failed to mark paper as viewed:', err));
        } catch (error) {
            console.log('Error marking paper as viewed:', error);
        }
    }

    // Store paper information in sessionStorage for the detail page
    sessionStorage.setItem(`paper_${paper.id}`, JSON.stringify(paper));

    // Determine if this is from search or recommendations using searchQuery
    const isFromSearch = searchQuery && searchQuery.trim().length > 0;

    let url = `paper.html?id=${paper.id}`;

    if (!isFromSearch) {
        // This is a recommendation - pass username to use blog_content API
        const currentUser = window.AuthService?.getCurrentUser();
        const username = currentUser?.username || 'BlogBot@gmail.com';
        url += `&username=${encodeURIComponent(username)}`;
    }
    // For search results: don't pass username to use paper_content API

    // Open paper detail page in new tab
    window.open(url, '_blank');
}

function showLoading() {
    loadingIndicator.style.display = 'block';
}

function hideLoading() {
    loadingIndicator.style.display = 'none';
}

function toggleTheme() {
    const body = document.body;
    const currentTheme = body.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    body.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// Utility function for debouncing
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// API service functions (similar to the original services)
class PaperService {
    static async getPapers() {
        try {
            // In a real implementation, this would make an HTTP request
            // const response = await fetch(`${API_BASE_URL}/papers?page=${page}&search=${search}`);
            // return await response.json();

            // For demo, return sample data
            return {
                papers: samplePapers,
                hasMore: false,
                total: samplePapers.length
            };
        } catch (error) {
            console.error('Error fetching papers:', error);
            throw error;
        }
    }

    static async getPaperDetail(paperId) {
        try {
            // const response = await fetch(`${API_BASE_URL}/papers/${paperId}`);
            // return await response.json();

            return samplePapers.find(p => p.id === paperId);
        } catch (error) {
            console.error('Error fetching paper detail:', error);
            throw error;
        }
    }

    static async getPaperContent() {
        try {
            // const response = await fetch(`${API_BASE_URL}/papers/${paperId}/content`);
            // return await response.json();

            // Return sample content (TigerVector content from the original service)
            return {
                content: `
## TigerVector: Bringing High-Performance Vector Search to Graph Databases for Advanced RAG

Retrieval-Augmented Generation (RAG) has become a cornerstone for grounding Large Language Models (LLMs) with external data. While traditional RAG often relies on vector databases storing semantic embeddings, this approach can struggle with complex queries that require understanding relationships between data points – a strength of graph databases.

Enter VectorGraphRAG, a promising hybrid approach that combines the power of vector search for semantic similarity with graph traversal for structural context. The paper "TigerVector: Supporting Vector Search in Graph Databases for Advanced RAGs" introduces TigerVector, a novel system that integrates vector search directly into TigerGraph, a distributed graph database.

### Key Innovations

**A Unified Data Model:** TigerVector introduces a new \`embedding\` attribute type for vertices. This isn't just a list of floats; it explicitly manages crucial metadata like dimensionality, the model used, index type, and similarity metric.

**Decoupled Storage:** Recognizing that vector embeddings are often much larger than other attributes, TigerVector stores vectors separately in "embedding segments." These segments mirror the vertex partitioning of the graph, ensuring related vector and graph data reside together for efficient processing.

**Leveraging MPP Architecture:** Built within TigerGraph's Massively Parallel Processing (MPP) architecture, TigerVector distributes vector data and processing across multiple machines. Vector indexes (currently supporting HNSW) are built per segment, and queries are parallelized, with results merged by a coordinator.
                `
            };
        } catch (error) {
            console.error('Error fetching paper content:', error);
            throw error;
        }
    }
}

// Setup authentication-based navigation
function setupAuthNavigation() {
    const profileLink = document.getElementById('profileLink');

    if (profileLink) {
        profileLink.addEventListener('click', (e) => {
            e.preventDefault();
            handleProfileNavigation();
        });
    }

    // Update navigation based on auth state
    updateNavigation();

    // Listen for auth state changes
    window.addEventListener('authStateChanged', (event) => {
        updateNavigation();

        // Reload papers when auth state changes
        if (event.detail.isLoggedIn) {
            loadUserRecommendations();
            loadUserFavorites(); // 用户登录时加载收藏
        } else {
            showLoginPrompt();
        }
    });
}

function handleProfileNavigation() {
    if (window.AuthService && window.AuthService.isLoggedIn()) {
        window.location.href = 'profile.html';
    } else {
        window.location.href = 'login.html';
    }
}

function updateNavigation() {
    const profileLink = document.getElementById('profileLink');
    if (!profileLink) return;

    if (window.AuthService && window.AuthService.isLoggedIn()) {
        const user = window.AuthService.getCurrentUser();
        profileLink.textContent = user?.username || 'Profile';
        profileLink.href = 'profile.html';
    } else {
        profileLink.textContent = 'Login';
        profileLink.href = 'login.html';
    }
}

/**
 * Format authors list - max 6 authors, then "et al"
 * @param {Array|string} authors - Authors array or string
 * @returns {string} Formatted authors string
 */
function formatAuthors(authors) {
    if (!authors) return 'Unknown authors';

    // Convert to array if string
    const authorsArray = Array.isArray(authors) ? authors : authors.split(', ');

    // Show max 6 authors
    const maxAuthors = 6;
    if (authorsArray.length <= maxAuthors) {
        return authorsArray.join(', ');
    }

    // Show first 6 + "et al"
    return authorsArray.slice(0, maxAuthors).join(', ') + ', et al.';
}
