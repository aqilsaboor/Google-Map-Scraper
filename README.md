# Google Maps Business Data Scraper

A powerful web scraping tool that extracts comprehensive business data from Google Maps, with real-time progress tracking and API integration capabilities.

## Features

- **Comprehensive Data Extraction**: Collect business names, addresses, phone numbers, websites, ratings, reviews, social media links, and more
- **Website Deep Dive**: Automatically visits business websites to extract emails, social media profiles, and structured data
- **Real-time Progress Tracking**: Monitor scraping progress through server-sent events
- **Facebook Integration**: Automatically scrapes connected Facebook pages to find additional contact information
- **API Integration**: Send collected data to your own API endpoint
- **Data Export**: Save results as CSV and JSON files for easy analysis
- **Review Analysis**: Collects both positive and negative reviews for sentiment analysis
- **Asynchronous Processing**: Handles multiple requests efficiently with asyncio and Playwright
- **Web Interface**: Simple browser-based interface for configuration and monitoring

## How It Works

1. Takes a search query (e.g., "Salons in Vienna")
2. Scrapes Google Maps for matching business listings
3. Visits each business's Google Maps page to extract detailed information
4. Analyzes each business's website for contact information, social media links, and structured data
5. Visits connected Facebook pages to extract additional email addresses
6. Compiles all data into structured CSV and JSON formats
7. Optionally sends data to a specified API endpoint

## Technical Details

- Built with Python and Playwright for robust browser automation
- Uses asyncio for non-blocking concurrent scraping
- Flask-based web interface with real-time progress updates using Server-Sent Events (SSE)
- BeautifulSoup for website content extraction
- Regex pattern matching for finding contact information
- Pandas for data manipulation and export

## Getting Started

### Prerequisites

- Python 3.7+
- Required packages: playwright, pandas, flask, requests, beautifulsoup4, tqdm, flask-cors

### Installation

1. Clone this repository
2. Install required packages:
   ```
   pip install -r requirements.txt
   ```
3. Install Playwright browsers:
   ```
   playwright install
   ```

### Usage

#### Web Interface

1. Start the server:
   ```
   python main.py
   ```
2. Open your browser and navigate to `http://localhost:5001`
3. Enter your search query and other settings
4. Click "Start Scraping" and monitor progress

#### Command Line

```
python main.py -s "Restaurants in New York" -t 100 -a "https://your-api.com/endpoint" -k "your-api-key"
```

Arguments:
- `-s` or `--search`: Search query
- `-t` or `--total`: Maximum number of results to scrape
- `-a` or `--api`: API endpoint to send data
- `-k` or `--key`: API key for authentication

## Configuration

You can set environment variables in a `.env` file:
- `PORT`: Server port (default: 5001)
- `HOST`: Server host (default: 0.0.0.0)
- `DEFAULT_SEARCH_QUERY`: Default search query
- `DEFAULT_RESULTS_COUNT`: Default number of results to scrape
- `DEFAULT_API_ENDPOINT`: Default API endpoint
- `DEFAULT_API_KEY`: Default API key

## Output Format

The scraper generates two files:
1. CSV file with basic business information
2. JSON file with detailed structured data, including website analysis

## Disclaimer

Use this tool responsibly and in accordance with Google's Terms of Service. Web scraping may be against the terms of service of some websites. This tool is for educational purposes only.

## License

[MIT License](LICENSE)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.