from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from .models import Movie, LikedMovie, WatchHistory, Watchlist, WatchlistMovie
import json
import os
import random
import pathlib
from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests
import logging
from django.core.paginator import Paginator
from django.db.models import Q
from .tmdb_utils import TMDBAPI
from django.contrib import messages
from functools import wraps
from django.urls import reverse

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

tmdb = TMDBAPI()

def get_recommendations(user):
    """Get movie recommendations based on user's watch history and liked movies."""
    if not user.is_authenticated:
        return []
    
    # Get movies from watch history and liked movies
    watched_movies = WatchHistory.objects.filter(user=user).values_list('movie', flat=True)
    liked_movies = LikedMovie.objects.filter(user=user).values_list('movie', flat=True)
    
    # Get genres of watched and liked movies
    watched_genres = Movie.objects.filter(id__in=watched_movies).values_list('genres', flat=True)
    liked_genres = Movie.objects.filter(id__in=liked_movies).values_list('genres', flat=True)
    
    # Combine and flatten genres
    all_genres = []
    for genres in watched_genres:
        if genres:
            all_genres.extend(genres)
    for genres in liked_genres:
        if genres:
            all_genres.extend(genres)
    
    # Get most common genres
    from collections import Counter
    genre_counter = Counter(all_genres)
    top_genres = [genre for genre, _ in genre_counter.most_common(3)]
    
    # Get movies with similar genres using string-based filtering
    recommended_movies = []
    for genre in top_genres:
        # Convert genre list to string for SQLite compatibility
        genre_movies = Movie.objects.filter(
            genres__icontains=genre
        ).exclude(
            id__in=watched_movies
        ).exclude(
            id__in=liked_movies
        ).distinct()[:10]
        recommended_movies.extend(genre_movies)
    
    # Remove duplicates and limit to 20 movies
    seen_ids = set()
    unique_movies = []
    for movie in recommended_movies:
        if movie.id not in seen_ids:
            seen_ids.add(movie.id)
            unique_movies.append(movie)
            if len(unique_movies) >= 20:
                break
    
    return unique_movies

def get_genre_movies():
    """Get movies grouped by genre."""
    genres = ['Action', 'Horror', 'Romance', 'Thriller', 'Comedy']
    genre_movies = {}
    
    for genre in genres:
        # Use string-based filtering for SQLite compatibility
        # Convert genre to lowercase for case-insensitive comparison
        genre_lower = genre.lower()
        
        # Get all movies and filter by genre
        movies = Movie.objects.all().order_by('-vote_average', '-vote_count')
        filtered_movies = []
        
        for movie in movies:
            # Get movie genres as a list and check if the genre is in the list
            movie_genres = [g.strip().lower() for g in movie.genres.split(',')]
            if genre_lower in movie_genres:
                filtered_movies.append(movie)
                if len(filtered_movies) >= 20:  # Limit to 20 movies per genre
                    break
        
        if filtered_movies:
            genre_movies[genre] = filtered_movies
    
    return genre_movies

def home(request):
    """Home page view with recommendations, popular movies, and genre lists."""
    try:
        # Try to get popular movies from TMDB
        popular_movies = []
        try:
            popular_movies_data = tmdb.get_popular_movies()
            if popular_movies_data and 'results' in popular_movies_data:
                for movie_data in popular_movies_data['results'][:20]:
                    try:
                        movie_details = tmdb.get_movie_details(movie_data['id'])
                        if movie_details:
                            movie = tmdb.save_movie_to_db(movie_details)
                            if movie:
                                popular_movies.append(movie)
                    except Exception as e:
                        logger.error(f"Error processing movie {movie_data.get('id')}: {str(e)}")
                        continue
        except Exception as e:
            logger.error(f"Error fetching popular movies: {str(e)}")
            # Fallback to cached popular movies if API fails
            popular_movies = Movie.objects.filter(
                vote_count__gt=1000
            ).order_by('-vote_average', '-vote_count')[:20]
        
        # Get recommendations for authenticated users
        recommended_movies = get_recommendations(request.user) if request.user.is_authenticated else []
        
        # Get genre-based movie lists
        genre_movies = get_genre_movies()
        
        context = {
            'popular_movies': popular_movies,
            'recommended_movies': recommended_movies,
            'genre_movies': genre_movies,
        }
        return render(request, 'core/home.html', context)
    except Exception as e:
        logger.error(f"Error in home view: {str(e)}")
        messages.error(request, "Failed to fetch movies. Please try again later.")
        return render(request, 'core/error.html', {'error': str(e)})

def movie_detail(request, movie_id):
    try:
        movie_data = tmdb.get_movie_details(movie_id)
        movie = tmdb.save_movie_to_db(movie_data)
        
        # Get similar movies
        similar_movies = []
        for similar_data in movie_data.get('similar', {}).get('results', [])[:6]:
            similar_movie = tmdb.save_movie_to_db(similar_data)
            similar_movies.append(similar_movie)
        
        # Get watch history if user is logged in
        watch_history = None
        if request.user.is_authenticated:
            watch_history = WatchHistory.objects.filter(
                user=request.user,
                movie=movie
            ).first()
        
        context = {
            'movie': movie,
            'similar_movies': similar_movies,
            'watch_history': watch_history,
            'is_liked': request.user.is_authenticated and 
                       LikedMovie.objects.filter(user=request.user, movie=movie).exists()
        }
        return render(request, 'core/movie_detail.html', context)
    except Exception as e:
        return render(request, 'core/error.html', {'error': str(e)})

@login_required
def like_movie(request, movie_id):
    if request.method == 'POST':
        movie = get_object_or_404(Movie, tmdb_id=movie_id)
        liked, created = LikedMovie.objects.get_or_create(user=request.user, movie=movie)
        
        if not created:
            liked.delete()
            return JsonResponse({'status': 'unliked'})
        
        return JsonResponse({'status': 'liked'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def update_watch_history(request, movie_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            movie = get_object_or_404(Movie, tmdb_id=movie_id)
            watch_duration = data.get('watch_duration', 0)
            completed = data.get('completed', False)
            
            watch_history, created = WatchHistory.objects.update_or_create(
                user=request.user,
                movie=movie,
                defaults={
                    'watch_duration': watch_duration,
                    'completed': completed
                }
            )
            
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Invalid request'}, status=400)

def login_required_with_modal(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse('home') + '?show_login=true')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@login_required_with_modal
def watch_history(request):
    """User's watch history view."""
    try:
        history = WatchHistory.objects.filter(user=request.user).select_related('movie').order_by('-watched_at')
        return render(request, 'core/watch_history.html', {'history': history})
    except Exception as e:
        logger.error(f"Error in watch history view: {str(e)}")
        messages.error(request, "Failed to load watch history. Please try again later.")
        return render(request, 'core/error.html', {'error': str(e)})

@login_required_with_modal
def liked_movies(request):
    """User's liked movies view."""
    try:
        liked_movies = LikedMovie.objects.filter(user=request.user).select_related('movie')
        return render(request, 'core/liked_movies.html', {'liked_movies': liked_movies})
    except Exception as e:
        logger.error(f"Error in liked movies view: {str(e)}")
        messages.error(request, "Failed to load liked movies. Please try again later.")
        return render(request, 'core/error.html', {'error': str(e)})

@login_required_with_modal
def library(request):
    try:
        # Get user's watchlist movies
        watchlist_movies = WatchlistMovie.objects.filter(
            watchlist__user=request.user
        ).select_related('movie').order_by('-added_at')

        # Get user's liked movies
        liked_movies = LikedMovie.objects.filter(
            user=request.user
        ).select_related('movie').order_by('-liked_at')

        context = {
            'watchlist_movies': watchlist_movies,
            'liked_movies': liked_movies,
        }
        return render(request, 'core/library.html', context)
    except Exception as e:
        logger.error(f"Error in library view: {str(e)}")
        return render(request, 'core/error.html', {'error': 'Unable to load your library. Please try again later.'})

def search_movies(request):
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    
    if query:
        try:
            results = tmdb.search_movies(query, page=int(page))
            movies = []
            for movie_data in results['results']:
                movie = tmdb.save_movie_to_db(movie_data)
                movies.append(movie)
            
            paginator = Paginator(movies, 20)
            movies_page = paginator.get_page(page)
            
            return render(request, 'core/search_results.html', {
                'movies': movies_page,
                'query': query,
                'total_pages': results['total_pages'],
                'current_page': int(page)
            })
        except Exception as e:
            return render(request, 'core/error.html', {'error': str(e)})
    
    return render(request, 'core/search_results.html', {'movies': []})

@login_required
def create_watchlist(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        privacy = request.POST.get('privacy', 'public')
        
        watchlist = Watchlist.objects.create(
            user=request.user,
            name=name,
            description=description,
            privacy=privacy
        )
        
        return redirect('watchlist_detail', watchlist_id=watchlist.id)
    return render(request, 'core/create_watchlist.html')

@login_required
def watchlist_detail(request, watchlist_id):
    watchlist = get_object_or_404(Watchlist, id=watchlist_id, user=request.user)
    movies = watchlist.movies.all()
    
    return render(request, 'core/watchlist_detail.html', {
        'watchlist': watchlist,
        'movies': movies
    })

@login_required
def add_to_watchlist(request, movie_id):
    """API endpoint to add movie to watchlist."""
    try:
        movie = get_object_or_404(Movie, tmdb_id=movie_id)
        watchlist = Watchlist.objects.get_or_create(user=request.user)[0]
        
        watchlist_movie, created = WatchlistMovie.objects.get_or_create(
            watchlist=watchlist,
            movie=movie
        )
        
        if created:
            message = f"{movie.title} added to your watchlist"
        else:
            watchlist_movie.delete()
            message = f"{movie.title} removed from your watchlist"
        
        return JsonResponse({
            'success': True,
            'message': message
        })
    except Exception as e:
        logger.error(f"Error in add to watchlist view: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def remove_from_watchlist(request, watchlist_id, movie_id):
    if request.method == 'POST':
        watchlist = get_object_or_404(Watchlist, id=watchlist_id, user=request.user)
        movie = get_object_or_404(Movie, tmdb_id=movie_id)
        
        WatchlistMovie.objects.filter(watchlist=watchlist, movie=movie).delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

def user_login(request):
    """Handle login requests via AJAX and regular form submissions."""
    if request.method == "POST":
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username_or_email or not password:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': "Please provide both username/email and password."
                })
            messages.error(request, "Please provide both username/email and password.")
            return redirect('login')
        
        # Try to authenticate with username first
        user = authenticate(request, username=username_or_email, password=password)
        
        # If username authentication fails, try email
        if user is None:
            try:
                username = User.objects.get(email=username_or_email).username
                user = authenticate(request, username=username, password=password)
            except User.DoesNotExist:
                user = None
        
        if user is not None:
            login(request, user)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True
                })
            return redirect('home')
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': "Invalid username/email or password."
            })
        messages.error(request, "Invalid username/email or password.")
        return redirect('login')
    
    # For GET requests, render the login page
    return render(request, 'core/registration/login.html')

@csrf_exempt
def signup(request):
    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            password = request.POST.get('password')
            password2 = request.POST.get('password2')

            # Validate input
            if not all([username, email, password, password2]):
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': "All fields are required!"
                    })
                messages.error(request, "All fields are required!")
                return redirect('register')

            if password != password2:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': "Passwords don't match!"
                    })
                messages.error(request, "Passwords don't match!")
                return redirect('register')

            # Check if username or email already exists
            if User.objects.filter(username=username).exists():
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': "Username already exists!"
                    })
                messages.error(request, "Username already exists!")
                return redirect('register')

            if User.objects.filter(email=email).exists():
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': "Email already registered!"
                    })
                messages.error(request, "Email already registered!")
                return redirect('register')

            # Create user
            user = User.objects.create_user(username=username, email=email, password=password)
            login(request, user)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': "Registration successful!",
                    'redirect': '/'
                })
            messages.success(request, "Registration successful!")
            return redirect('home')
            
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': "Registration failed. Please try again."
                })
            messages.error(request, "Registration failed. Please try again.")
            return redirect('register')

    return render(request, 'core/register.html')

def user_logout(request):
    """Custom logout view that handles both GET and POST requests."""
    logout(request)
    return redirect('home')


def register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')

        # Validate input
        if not all([username, email, password, password2]):
            return JsonResponse({
                'success': False,
                'error': "All fields are required!"
            })

        if password != password2:
            return JsonResponse({
                'success': False,
                'error': "Passwords don't match!"
            })

        if len(password) < 8:
            return JsonResponse({
                'success': False,
                'error': "Password must be at least 8 characters long!"
            })

        # Check if username or email already exists
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'success': False,
                'error': "Username already exists!"
            })

        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False,
                'error': "Email already registered!"
            })

        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            login(request, user)
            return JsonResponse({
                'success': True
            })
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': "Registration failed. Please try again."
            })

    return JsonResponse({
        'success': False,
        'error': "Invalid request method."
    })

def genre_movies(request, genre):
    """View for movies of a specific genre."""
    try:
        # Convert genre to proper case for display
        genre_display = genre.capitalize()
        genre_lower = genre.lower()
        
        # Get movies with this genre
        movies = Movie.objects.filter(
            genres__icontains=genre_lower
        ).order_by('-vote_average', '-vote_count')
        
        # Filter out movies that don't actually have this genre
        filtered_movies = []
        for movie in movies:
            movie_genres = [g.strip().lower() for g in movie.genres.split(',')]
            if genre_lower in movie_genres:
                filtered_movies.append(movie)
        
        # Add pagination
        paginator = Paginator(filtered_movies, 20)
        page = request.GET.get('page', 1)
        try:
            movies_page = paginator.page(page)
        except (PageNotAnInteger, EmptyPage):
            movies_page = paginator.page(1)
        
        context = {
            'genre': genre_display,
            'movies': movies_page,
            'total_pages': paginator.num_pages,
            'current_page': int(page)
        }
        return render(request, 'core/genre_movies.html', context)
    except Exception as e:
        logger.error(f"Error in genre movies view: {str(e)}")
        messages.error(request, f"Failed to load {genre_display} movies. Please try again later.")
        return render(request, 'core/error.html', {'error': str(e)})

def search(request):
    """Search movies view."""
    query = request.GET.get('q', '').strip()
    if not query:
        return redirect('home')
    
    try:
        # Search in TMDB API
        search_data = tmdb.search_movies(query)
        movies = []
        for movie_data in search_data.get('results', []):
            movie = tmdb.save_movie_to_db(movie_data)
            movies.append(movie)
        
        return render(request, 'core/search_results.html', {
            'query': query,
            'movies': movies
        })
    except Exception as e:
        logger.error(f"Error in search view: {str(e)}")
        messages.error(request, "Search failed. Please try again later.")
        return render(request, 'core/error.html', {'error': str(e)})

@login_required
def movie_details(request, movie_id):
    """API endpoint for movie details including video."""
    try:
        if not movie_id or not str(movie_id).isdigit():
            return JsonResponse({
                'error': 'Invalid movie ID'
            }, status=400)
        
        # Try to get movie from database first
        movie = Movie.objects.filter(tmdb_id=movie_id).first()
        
        if not movie:
            # If not in database, try to fetch from TMDB
            try:
                movie_data = tmdb.get_movie_details(movie_id)
                if movie_data:
                    movie = tmdb.save_movie_to_db(movie_data)
            except Exception as e:
                logger.error(f"Error fetching movie details from TMDB: {str(e)}")
                return JsonResponse({
                    'error': 'Failed to fetch movie details. Please try again later.'
                }, status=503)
        
        if not movie:
            return JsonResponse({
                'error': 'Movie not found'
            }, status=404)
            
        # Try to get video (trailer) from TMDB
        video_url = None
        try:
            video_data = tmdb.get_movie_videos(movie_id)
            if video_data and 'results' in video_data:
                for video in video_data['results']:
                    if video.get('type') == 'Trailer' and video.get('site') == 'YouTube':
                        video_url = f"https://www.youtube.com/embed/{video['key']}"
                        break
        except Exception as e:
            logger.error(f"Error fetching video data: {str(e)}")
            # Continue without video if API fails
        
        # Check if movie is liked by user
        is_liked = LikedMovie.objects.filter(user=request.user, movie=movie).exists()
        
        # Add to watch history
        WatchHistory.objects.create(user=request.user, movie=movie)
        
        return JsonResponse({
            'title': movie.title,
            'poster_path': movie.poster_path,
            'release_date': movie.release_date.strftime('%B %d, %Y') if movie.release_date else None,
            'vote_average': movie.vote_average,
            'vote_count': movie.vote_count,
            'runtime': movie.runtime,
            'genres': movie.genres.split(',') if movie.genres else [],
            'overview': movie.overview,
            'video_url': video_url,
            'is_liked': is_liked
        })
    except Exception as e:
        logger.error(f"Error in movie details view: {str(e)}")
        return JsonResponse({
            'error': 'An error occurred while fetching movie details'
        }, status=500)

@login_required
def toggle_like(request, movie_id):
    """API endpoint to toggle movie like status."""
    try:
        if not movie_id or not str(movie_id).isdigit():
            return JsonResponse({
                'error': 'Invalid movie ID'
            }, status=400)
            
        movie = get_object_or_404(Movie, tmdb_id=movie_id)
        liked_movie, created = LikedMovie.objects.get_or_create(user=request.user, movie=movie)
        
        if not created:
            liked_movie.delete()
            is_liked = False
        else:
            is_liked = True
        
        return JsonResponse({
            'success': True,
            'is_liked': is_liked,
            'message': 'Movie liked' if is_liked else 'Movie unliked'
        })
    except Movie.DoesNotExist:
        return JsonResponse({
            'error': 'Movie not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error in toggle like view: {str(e)}")
        return JsonResponse({
            'error': 'An error occurred while updating like status'
        }, status=500)

@login_required
def clear_watch_history(request):
    """Clear all watch history for the current user."""
    if request.method == 'POST':
        try:
            WatchHistory.objects.filter(user=request.user).delete()
            return JsonResponse({'success': True, 'message': 'Watch history cleared successfully'})
        except Exception as e:
            logger.error(f"Error clearing watch history: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)

@login_required
def remove_from_history(request, movie_id):
    """Remove a specific movie from watch history."""
    if request.method == 'POST':
        try:
            movie = get_object_or_404(Movie, tmdb_id=movie_id)
            WatchHistory.objects.filter(user=request.user, movie=movie).delete()
            return JsonResponse({'success': True, 'message': 'Movie removed from history'})
        except Exception as e:
            logger.error(f"Error removing movie from history: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
