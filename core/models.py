from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Movie(models.Model):
    tmdb_id = models.IntegerField(unique=True)
    title = models.CharField(max_length=200)
    overview = models.TextField()
    poster_path = models.URLField(null=True, blank=True)
    backdrop_path = models.URLField(null=True, blank=True)
    release_date = models.DateField()
    vote_average = models.FloatField()
    vote_count = models.IntegerField()
    genres = models.TextField()  # Store as comma-separated string
    runtime = models.IntegerField(null=True)
    language = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_genres_list(self):
        """Convert comma-separated genres string to list."""
        return [genre.strip() for genre in self.genres.split(',') if genre.strip()]

    def set_genres_list(self, genres_list):
        """Convert list of genres to comma-separated string."""
        self.genres = ','.join(str(genre).strip() for genre in genres_list)

    def __str__(self):
        return self.title

class LikedMovie(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='liked_movies')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='liked_by')
    liked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'movie')

    def __str__(self):
        return f"{self.movie.title} - {self.user.username}"

class WatchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watch_history')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='watched_by')
    watched_at = models.DateTimeField(auto_now_add=True)
    watch_duration = models.IntegerField(default=0)  # Duration in seconds
    completed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-watched_at']
        verbose_name_plural = 'Watch History'

    def __str__(self):
        return f"{self.movie.title} watched by {self.user.username}"

class Watchlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlists')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    privacy = models.CharField(max_length=10, choices=[('public', 'Public'), ('private', 'Private')], default='public')
    created_at = models.DateTimeField(auto_now_add=True)
    movies = models.ManyToManyField(Movie, through='WatchlistMovie')

    def __str__(self):
        return self.name

class WatchlistMovie(models.Model):
    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('watchlist', 'movie')

    def __str__(self):
        return f"{self.movie.title} in {self.watchlist.name}"
