"""
Sonarr API integration module.

Provides functions for interacting with Sonarr's API to add and manage series.
"""

import logging
import requests
from typing import Dict, List, Optional, Any
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def _create_session(verify_ssl: bool = True) -> requests.Session:
    """Create a requests session with a conservative retry policy."""
    session = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.verify = verify_ssl
    return session


def _extract_error_message(response: requests.Response) -> str:
    """Extract a useful error message from JSON or plain-text API responses."""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error")
            if message:
                return str(message)
    except ValueError:
        pass

    return (response.text or "").strip()


class SonarrError(Exception):
    """Base exception for Sonarr API errors."""
    pass


class SonarrConnectionError(SonarrError):
    """Raised when connection to Sonarr fails."""
    pass


class SonarrAuthenticationError(SonarrError):
    """Raised when API key authentication fails."""
    pass


def test_connection(url: str, api_key: str, timeout: int = 10, verify_ssl: bool = True) -> Dict[str, Any]:
    """
    Test connection to Sonarr and retrieve system status.
    
    Args:
        url: Sonarr base URL (e.g., http://localhost:8989)
        api_key: Sonarr API key
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        Dict with system status information
        
    Raises:
        SonarrConnectionError: If connection fails
        SonarrAuthenticationError: If API key is invalid
    """
    session = None
    try:
        endpoint = f"{url.rstrip('/')}/api/v3/system/status"
        headers = {"X-Api-Key": api_key}
        
        session = _create_session(verify_ssl=verify_ssl)
        response = session.get(endpoint, headers=headers, timeout=timeout)
        
        if response.status_code == 401:
            raise SonarrAuthenticationError("Invalid API key")
        
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.Timeout:
        raise SonarrConnectionError(f"Connection timeout after {timeout}s")
    except requests.exceptions.ConnectionError as e:
        raise SonarrConnectionError(f"Failed to connect to Sonarr: {e}")
    except SonarrAuthenticationError:
        raise
    except Exception as e:
        raise SonarrConnectionError(f"Unexpected error: {e}")
    finally:
        if session is not None:
            session.close()


def search_series(url: str, api_key: str, title: str, timeout: int = 10, verify_ssl: bool = True) -> List[Dict[str, Any]]:
    """
    Search for a series in Sonarr's indexers.
    
    Args:
        url: Sonarr base URL
        api_key: Sonarr API key
        title: Series title to search for
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        List of matching series with metadata
        
    Raises:
        SonarrError: If search fails
    """
    session = None
    try:
        endpoint = f"{url.rstrip('/')}/api/v3/series/lookup"
        headers = {"X-Api-Key": api_key}
        params = {"term": title}
        
        session = _create_session(verify_ssl=verify_ssl)
        response = session.get(endpoint, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        
        results = response.json()
        logger.info(f"Found {len(results)} results for '{title}'")
        return results
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Series search failed: {e}")
        raise SonarrError(f"Search failed: {e}")
    finally:
        if session is not None:
            session.close()


def get_quality_profiles(url: str, api_key: str, timeout: int = 10, verify_ssl: bool = True) -> List[Dict[str, Any]]:
    """
    Get available quality profiles from Sonarr.
    
    Args:
        url: Sonarr base URL
        api_key: Sonarr API key
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        List of quality profiles
        
    Raises:
        SonarrError: If request fails
    """
    session = None
    try:
        endpoint = f"{url.rstrip('/')}/api/v3/qualityprofile"
        headers = {"X-Api-Key": api_key}
        
        session = _create_session(verify_ssl=verify_ssl)
        response = session.get(endpoint, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        return response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get quality profiles: {e}")
        raise SonarrError(f"Failed to get quality profiles: {e}")
    finally:
        if session is not None:
            session.close()


def get_root_folders(url: str, api_key: str, timeout: int = 10, verify_ssl: bool = True) -> List[Dict[str, Any]]:
    """
    Get available root folders from Sonarr.
    
    Args:
        url: Sonarr base URL
        api_key: Sonarr API key
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        List of root folders
        
    Raises:
        SonarrError: If request fails
    """
    session = None
    try:
        endpoint = f"{url.rstrip('/')}/api/v3/rootfolder"
        headers = {"X-Api-Key": api_key}
        
        session = _create_session(verify_ssl=verify_ssl)
        response = session.get(endpoint, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        return response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get root folders: {e}")
        raise SonarrError(f"Failed to get root folders: {e}")
    finally:
        if session is not None:
            session.close()


def add_series(
    url: str,
    api_key: str,
    series_data: Dict[str, Any],
    quality_profile_id: int,
    root_folder_path: str,
    monitor: str = "all",
    search_for_missing: bool = False,
    timeout: int = 30,
    verify_ssl: bool = True,
) -> Dict[str, Any]:
    """
    Add a series to Sonarr.
    
    Args:
        url: Sonarr base URL
        api_key: Sonarr API key
        series_data: Series metadata from search_series()
        quality_profile_id: Quality profile ID to use
        root_folder_path: Root folder path for downloads
        monitor: Monitoring mode ('all', 'future', 'missing', 'existing', 'none')
        search_for_missing: Whether to search for missing episodes immediately
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        Added series data
        
    Raises:
        SonarrError: If add fails
    """
    session = None
    try:
        endpoint = f"{url.rstrip('/')}/api/v3/series"
        headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }
        
        # Prepare payload
        payload = {
            "title": series_data.get("title"),
            "titleSlug": series_data.get("titleSlug"),
            "tvdbId": series_data.get("tvdbId"),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": True,
            "addOptions": {
                "monitor": monitor,
                "searchForMissingEpisodes": search_for_missing
            }
        }
        
        # Copy other metadata
        for key in ["images", "seasons", "year", "profileId"]:
            if key in series_data:
                payload[key] = series_data[key]
        
        session = _create_session(verify_ssl=verify_ssl)
        response = session.post(endpoint, headers=headers, json=payload, timeout=timeout)
        
        # Check for duplicate (400 with specific message)
        if response.status_code == 400:
            error_msg = _extract_error_message(response)
            if "already" in error_msg.lower():
                raise SonarrError(f"Series already exists: {series_data.get('title')}")
        
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"Successfully added series: {result.get('title')}")
        return result
        
    except SonarrError:
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to add series: {e}")
        raise SonarrError(f"Failed to add series: {e}")
    finally:
        if session is not None:
            session.close()


def bulk_add_series(
    url: str,
    api_key: str,
    series_list: List[Dict[str, Any]],
    quality_profile_id: int,
    root_folder_path: str,
    monitor: str = "all",
    search_for_missing: bool = False,
    verify_ssl: bool = True,
) -> Dict[str, List[str]]:
    """
    Bulk add multiple series to Sonarr.
    
    Args:
        url: Sonarr base URL
        api_key: Sonarr API key
        series_list: List of series metadata from search_series()
        quality_profile_id: Quality profile ID to use
        root_folder_path: Root folder path for downloads
        monitor: Monitoring mode
        search_for_missing: Whether to search for missing episodes
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        Dict with 'success' and 'failed' lists of series titles
    """
    results = {
        "success": [],
        "failed": []
    }
    
    for series_data in series_list:
        title = series_data.get("title", "Unknown")
        try:
            add_series(
                url, api_key, series_data,
                quality_profile_id, root_folder_path,
                monitor, search_for_missing,
                verify_ssl=verify_ssl,
            )
            results["success"].append(title)
        except SonarrError as e:
            logger.error(f"Failed to add {title}: {e}")
            results["failed"].append(f"{title}: {str(e)}")
    
    return results


__all__ = [
    'SonarrError',
    'SonarrConnectionError',
    'SonarrAuthenticationError',
    'test_connection',
    'search_series',
    'get_quality_profiles',
    'get_root_folders',
    'add_series',
    'bulk_add_series'
]
