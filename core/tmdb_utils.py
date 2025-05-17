import requests
from django.conf import settings
from datetime import datetime, timedelta
from .models import Movie
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3 import PoolManager
import time
import logging
from django.core.cache import cache
import random
import socket
from urllib3.exceptions import ProtocolError, ReadTimeoutError

logger = logging.getLogger(__name__)

class TMDBAPI:
    def __init__(self):
        self.base_url = 'https://api.themoviedb.org/3'
        self.image_base_url = 'https://image.tmdb.org/t/p'
        self.api_key = settings.TMDB_API_KEY
        self.cache_timeout = 3600  # Cache results for 1 hour
        
        # Configure retry strategy with more aggressive settings
        retry_strategy = Retry(
            total=5,  # Reduced total retries but with better backoff
            backoff_factor=0.3,  # Faster initial retries
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            respect_retry_after_header=True,
            raise_on_status=False
        )
        
        # Create a custom connection pool with persistent connections
        self.pool = PoolManager(
            maxsize=10,
            retries=retry_strategy,
            timeout=3.05,  # Fixed timeout value
            socket_options=[
                (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
                (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),
                (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10),
                (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
            ]
        )
        
        # Create session with the custom pool
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            pool_block=False,
            max_retries=retry_strategy
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Set default headers
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Sonic/1.0',
            'Connection': 'keep-alive',
            'Accept-Encoding': 'gzip, deflate',
            'Keep-Alive': 'timeout=60, max=1000'
        })

    def _make_request(self, endpoint, params=None):
        """Make a request to the TMDB API with improved error handling and retries."""
        if params is None:
            params = {}
        
        params['api_key'] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        cache_key = f'tmdb_cache_{endpoint}_{hash(str(params))}'
        
        # Try to get from cache first
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"Retrieved {endpoint} from cache")
            return cached_data
        
        try:
            # Add small random delay to prevent thundering herd
            time.sleep(random.uniform(0.1, 0.3))
            
            # Make the request with proper error handling
            response = self.session.get(
                url,
                params=params,
                timeout=(3.05, 27),  # (connect timeout, read timeout)
                verify=True
            )
            
            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 1))
                logger.warning(f"Rate limited. Waiting {retry_after} seconds.")
                time.sleep(retry_after)
                return self._make_request(endpoint, params)
            
            # Handle other status codes
            if response.status_code != 200:
                logger.error(f"TMDB API returned status code {response.status_code}")
                if cached_data:
                    logger.info(f"Returning cached data for {endpoint}")
                    return cached_data
                raise requests.exceptions.HTTPError(f"TMDB API returned status code {response.status_code}")
            
            data = response.json()
            
            # Cache successful response
            cache.set(cache_key, data, timeout=self.cache_timeout)
            logger.info(f"Successfully fetched {endpoint}")
            return data
            
        except (requests.exceptions.RequestException, ProtocolError, ReadTimeoutError) as e:
            logger.error(f"TMDB API request failed: {str(e)}")
            
            # Return cached data if available
            if cached_data:
                logger.info(f"Returning cached data for {endpoint} after error")
                return cached_data
            
            # If no cached data, raise the exception
            raise

    def get_popular_movies(self, page=1):
        """Get popular movies with caching."""
        cache_key = f'tmdb_popular_movies_{page}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Retrieved popular movies from cache for page {page}")
            return cached_data

        try:
            data = self._make_request('movie/popular', {'page': page})
            cache.set(cache_key, data, timeout=3600)  # Cache for 1 hour
            logger.info(f"Successfully fetched popular movies for page {page}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch popular movies: {str(e)}")
            return None

    def search_movies(self, query, page=1):
        """Search movies with caching."""
        cache_key = f'tmdb_search_{query}_{page}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Retrieved search results from cache for query: {query}")
            return cached_data

        try:
            data = self._make_request('search/movie', {
                'query': query,
                'page': page
            })
            cache.set(cache_key, data, timeout=1800)  # Cache for 30 minutes
            logger.info(f"Successfully searched movies for query: {query}")
            return data
        except Exception as e:
            logger.error(f"Failed to search movies for query '{query}': {str(e)}")
            return None

    def get_movie_details(self, movie_id):
        """Get movie details with caching."""
        cache_key = f'tmdb_movie_{movie_id}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Retrieved movie details from cache for movie {movie_id}")
            return cached_data

        try:
            data = self._make_request(f'movie/{movie_id}', {
                'append_to_response': 'videos,credits,similar'
            })
            cache.set(cache_key, data, timeout=3600)  # Cache for 1 hour
            logger.info(f"Successfully fetched details for movie {movie_id}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch movie details for {movie_id}: {str(e)}")
            return None

    def get_movie_credits(self, movie_id):
        """Get movie credits with improved error handling."""
        try:
            return self._make_request(f'movie/{movie_id}/credits')
        except Exception as e:
            logger.error(f"Error fetching movie credits: {str(e)}")
            return None

    def get_movie_videos(self, movie_id):
        """Get movie videos with caching."""
        cache_key = f'tmdb_movie_videos_{movie_id}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Retrieved movie videos from cache for movie {movie_id}")
            return cached_data

        try:
            data = self._make_request(f'movie/{movie_id}/videos')
            cache.set(cache_key, data, timeout=3600)  # Cache for 1 hour
            logger.info(f"Successfully fetched videos for movie {movie_id}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch movie videos for {movie_id}: {str(e)}")
            return None

    def _process_movie_list(self, movies):
        """Process movie list to add poster URLs and clean data."""
        processed_movies = []
        for movie in movies:
            if movie.get('poster_path'):
                movie['poster_path'] = f"{self.image_base_url}/w500{movie['poster_path']}"
            else:
                movie['poster_path'] = '/static/images/no-poster.jpg'
            processed_movies.append(movie)
        return processed_movies

    def get_poster_url(self, poster_path, size='w500'):
        if not poster_path:
            return None
        return f"{self.image_base_url}/{size}{poster_path}"

    def get_backdrop_url(self, backdrop_path, size='original'):
        if not backdrop_path:
            return None
        return f"{self.image_base_url}/{size}{backdrop_path}"

    def save_movie_to_db(self, movie_data):
        """Save or update movie in database with improved error handling."""
        try:
            # Extract genres as a list of names
            genres = [genre['name'] for genre in movie_data.get('genres', [])]
            
            # Format poster and backdrop paths with TMDB image base URL
            poster_path = movie_data.get('poster_path')
            backdrop_path = movie_data.get('backdrop_path')
            
            if poster_path:
                poster_path = f"{self.image_base_url}/w500{poster_path}"
            else:
                poster_path = '/static/images/no-poster.jpg'
                
            if backdrop_path:
                backdrop_path = f"{self.image_base_url}/original{backdrop_path}"
            
            # Get or create movie
            movie, created = Movie.objects.update_or_create(
                tmdb_id=movie_data['id'],
                defaults={
                    'title': movie_data['title'],
                    'overview': movie_data.get('overview', ''),
                    'poster_path': poster_path,
                    'backdrop_path': backdrop_path,
                    'release_date': movie_data.get('release_date'),
                    'vote_average': movie_data.get('vote_average', 0),
                    'vote_count': movie_data.get('vote_count', 0),
                    'runtime': movie_data.get('runtime', 0),
                    'genres': ','.join(genres),  # Store genres as comma-separated string
                    'language': movie_data.get('original_language', 'en'),
                    'updated_at': datetime.now()
                }
            )
            
            if created:
                logger.info(f"Created new movie: {movie.title}")
            else:
                logger.info(f"Updated existing movie: {movie.title}")
            
            return movie
        except Exception as e:
            logger.error(f"Failed to save movie to database: {str(e)}")
            raise

    def get_movie_recommendations(self, movie_id, page=1):
        try:
            return self._make_request(f'movie/{movie_id}/recommendations', {'page': page})
        except Exception as e:
            raise Exception(f"Failed to fetch movie recommendations: {str(e)}")

    def get_upcoming_movies(self, page=1):
        try:
            return self._make_request('movie/upcoming', {'page': page})
        except Exception as e:
            raise Exception(f"Failed to fetch upcoming movies: {str(e)}")

    def get_top_rated_movies(self, page=1):
        try:
            return self._make_request('movie/top_rated', {'page': page})
        except Exception as e:
            raise Exception(f"Failed to fetch top rated movies: {str(e)}")

# Create a singleton instance
tmdb_api = TMDBAPI() 