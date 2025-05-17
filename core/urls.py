from django.urls import path, include
from django.contrib import admin
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('library/', views.library, name='library'),
    path('login/', views.user_login, name='login'),
    path('register/', views.register, name='register'),
    path('signup/', views.signup, name='signup'),
    path('logout/', views.user_logout, name='logout'),
    path('movie/<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('movie/<int:movie_id>/like/', views.like_movie, name='like_movie'),
    path('movie/<int:movie_id>/watch-history/', views.update_watch_history, name='update_watch_history'),
    path('watch-history/', views.watch_history, name='watch_history'),
    path('liked-movies/', views.liked_movies, name='liked_movies'),
    path('search/movies/', views.search_movies, name='search_movies'),
    path('watchlist/create/', views.create_watchlist, name='create_watchlist'),
    path('watchlist/<int:watchlist_id>/', views.watchlist_detail, name='watchlist_detail'),
    path('watchlist/<int:watchlist_id>/add/<int:movie_id>/', views.add_to_watchlist, name='add_to_watchlist'),
    path('watchlist/<int:watchlist_id>/remove/<int:movie_id>/', views.remove_from_watchlist, name='remove_from_watchlist'),
    path('genre/<str:genre>/', views.genre_movies, name='genre_movies'),
    path('api/movie/<int:movie_id>/', views.movie_details, name='movie_details'),
    path('api/movie/<int:movie_id>/like/', views.toggle_like, name='toggle_like'),
    path('api/movie/<int:movie_id>/watchlist/', views.add_to_watchlist, name='add_to_watchlist'),
    path('admin/', admin.site.urls),
    path('api/history/clear/', views.clear_watch_history, name='clear_watch_history'),
    path('api/history/remove/<int:movie_id>/', views.remove_from_history, name='remove_from_history'),
]
