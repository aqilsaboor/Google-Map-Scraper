from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import pandas as pd
import argparse
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
from typing import Dict, List, Optional
import time
import os
from tqdm import tqdm
from flask import Flask, Response, request, send_file
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import traceback
import asyncio  # Add asyncio import
from flask_cors import CORS
# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, template_folder='templates')
CORS(app, resources={r"/*": {"origins": "*"}})
update_queue = queue.Queue()


@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    try:
        # Check if file exists in the current directory
        if not os.path.exists(filename):
            return {"status": "error", "message": f"File {filename} not found"}, 404
        
        # Return the file as an attachment
        return send_file(filename, 
                         mimetype='text/csv',
                         as_attachment=True,
                         download_name=filename)
    except Exception as e:
        return {"status": "error", "message": f"Error downloading file: {str(e)}"}, 500
    
# SSE route to stream progress updates
@app.route('/stream')
def stream():
    def event_stream():
        while True:
            message = update_queue.get()
            if message == "DONE":
                yield "data: {\"status\": \"complete\"}\n\n"
                break
            yield f"data: {json.dumps(message)}\n\n"
    
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/scrape', methods=['GET'])
def scrape():
    # Get parameters from URL query string
    search_query = request.args.get('search_query', f'Salon in austria')
    total_results = int(request.args.get('total_results', 1000))
    api_endpoint = request.args.get('api_endpoint', f'http://3.75.61.76:3000/api/google-maps?searchTerm={search_query}')
    api_key = request.args.get('api_key', '')

    # Store parameters in app context
    app.config['SCRAPE_PARAMS'] = {
        'search_query': search_query,
        'total_results': total_results,
        'api_endpoint': api_endpoint,
        'api_key': api_key
    }

    # Clear any existing queue
    while not update_queue.empty():
            update_queue.get()

        
    # With this solution:
    def thread_worker(search_query, total_results, api_endpoint, api_key):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_scraper(search_query, total_results, api_endpoint, api_key))
        finally:
            loop.close()

    # Then start the thread with this worker function
    threading.Thread(target=thread_worker, args=(search_query, total_results, api_endpoint, api_key)).start()
    def event_stream():
        while True:
            message = update_queue.get()
            if message == "DONE":
                yield "data: {\"status\": \"complete\"}\n\n"
                break
            yield f"data: {json.dumps(message)}\n\n"
    
    return Response(event_stream(), mimetype="text/event-stream")

# Function to send updates to the client
def send_update(message):
    update_queue.put(message)



class WebsiteDataExtractor:
    def __init__(self):
        self.patterns = {
            'email': r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',
            'phone': r'(\+\d{1,3}[-.]?)?\s*\(?\d{3}\)?[-.]?\s*\d{3}[-.]?\s*\d{4}',
            'social_media': {
                'facebook': r'facebook\.com/[A-Za-z0-9.]+',
                'instagram': r'instagram\.com/[A-Za-z0-9_]+',
                'twitter': r'twitter\.com/[A-Za-z0-9_]+',
                'linkedin': r'linkedin\.com/[A-Za-z0-9_]+',
                'youtube': r'youtube\.com/[A-Za-z0-9_]+',
            }
        }

    def extract_structured_data(self, url: str) -> Dict:
        if not url or url == "N/A" or url == "Null":
            return self._get_empty_result()
        try:
            session = self._create_session()
            soup = self._get_page_content(url, session)
            data = {
                'url': url,
                'structured_data': self._extract_schema_data(soup),
                'meta_data': self._extract_meta_data(soup),
                'contact_info': self._extract_contact_info(soup, url, session),
                'social_media': self._extract_social_media(soup),
                'business_hours': self._extract_business_hours(soup),
                'additional_info': self._extract_additional_info(soup)
            }
            return data
        except Exception as e:
            send_update({"status": "error", "message": f"Error extracting data from {url}: {str(e)}"})
            return self._get_empty_result()

    def _create_session(self):
        session = requests.Session()
        session.verify = False
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        return session

    def _get_page_content(self, url: str, session) -> BeautifulSoup:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        for attempt in range(3):
            try:
                response = session.get(url, timeout=20)
                return BeautifulSoup(response.text, 'html.parser')
            except:
                if attempt == 2:
                    raise
                time.sleep(1)

    def _extract_schema_data(self, soup: BeautifulSoup) -> Dict:
        schema_data = {}
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    schema_data.update(data)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            schema_data.update(item)
            except:
                continue
        return schema_data

    def _extract_meta_data(self, soup: BeautifulSoup) -> Dict:
        meta_data = {}
        for meta in soup.find_all('meta'):
            name = meta.get('name', meta.get('property', ''))
            content = meta.get('content', '')
            if name and content:
                meta_data[name] = content
        return meta_data

    def _extract_contact_info(self, soup: BeautifulSoup, url: str, session) -> Dict:
        contact_info = {'emails': [], 'phones': [], 'address': None}
        text = soup.get_text()
        contact_info['emails'] = self._extract_emails(text)
        contact_info['phones'] = self._extract_phones(text)
        contact_links = soup.find_all('a', href=re.compile(r'contact|about|get-in-touch|reach-us', re.I))
        for link in contact_links[:2]:
            try:
                contact_url = urljoin(url, link['href'])
                response = session.get(contact_url, timeout=10)
                contact_soup = BeautifulSoup(response.text, 'html.parser')
                contact_text = contact_soup.get_text()
                contact_info['emails'].extend(self._extract_emails(contact_text))
                contact_info['phones'].extend(self._extract_phones(contact_text))
            except:
                continue
        contact_info['emails'] = list(set(contact_info['emails']))
        contact_info['phones'] = list(set(contact_info['phones']))
        return contact_info

    def _extract_social_media(self, soup: BeautifulSoup) -> Dict:
        social_media = {}
        for platform, pattern in self.patterns['social_media'].items():
            links = soup.find_all('a', href=re.compile(pattern, re.I))
            if links:
                social_media[platform] = list(set([link['href'] for link in links]))
        return social_media

    def _extract_business_hours(self, soup: BeautifulSoup) -> Optional[Dict]:
        schema_data = self._extract_schema_data(soup)
        if 'openingHours' in schema_data:
            return schema_data['openingHours']
        hours_div = soup.find('div', class_=re.compile(r'hours|schedule|timing', re.I))
        if hours_div:
            return {'raw': hours_div.get_text(strip=True)}
        return {}

    def _extract_additional_info(self, soup: BeautifulSoup) -> Dict:
        info = {}
        price_range = soup.find(class_=re.compile(r'price-range|pricing', re.I))
        if price_range:
            info['price_range'] = price_range.get_text(strip=True)
        cuisine = soup.find(class_=re.compile(r'cuisine|food-type', re.I))
        if cuisine:
            info['cuisine'] = cuisine.get_text(strip=True)
        return info

    def _extract_emails(self, text: str) -> List[str]:
        emails = re.findall(self.patterns['email'], text)
        return [email for email in emails if not email.endswith(('.png', '.jpg', '.gif', '.jpeg')) and len(email) < 100]

    def _extract_phones(self, text: str) -> List[str]:
        return re.findall(self.patterns['phone'], text)

    def _get_empty_result(self) -> Dict:
        return {'url': None, 'structured_data': {}, 'meta_data': {}, 'contact_info': {'emails': [], 'phones': [], 'address': None}, 'social_media': {}, 'business_hours': {}, 'additional_info': {}}

# Function to send data to API
def send_to_api(data, api_endpoint, api_key=None):
    if not api_endpoint:
        send_update({"status": "warning", "message": "No API endpoint provided. Skipping API submission."})
        return False
    
    try:
        headers = {
            'Content-Type': 'application/json'
        }
        
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        
        send_update({"status": "info", "message": f"Sending data to API"})
        response = requests.post(api_endpoint, json=data, headers=headers, timeout=30)
        
        if response.status_code >= 200 and response.status_code < 300:
            send_update({"status": "success", "message": f"Data successfully sent to API. Response: {response.status_code}"})
            return True
        else:
            send_update({"status": "error", "message": f"API request failed with status code: {response.status_code}, Response: {response.text}"})
            return False
    
    except Exception as e:
        send_update({"status": "error", "message": f"Error sending data to API: {str(e)}"})
        return False
    
# def listing_scraper(args):
#     # Create a new event loop for this thread
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
    
#     try:
#         # Run the async function in this thread's event loop
#         result = loop.run_until_complete(_listing_scraper(args))
#         return result
#     finally:
#         loop.close()
async def async_listing_scraper(args, browser):
    idx, listing_href, len_listings, search_for, timeout_count = args
    try:
        page = await browser.new_page()
        await page.set_viewport_size({"width": 1920, "height": 1080})
        try:
            name_xpath = '//div[@class="TIHn2 "]//h1[@class="DUwDvf lfPIob"]'
            address_xpath = '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]'
            website_xpath = '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]'
            phone_number_xpath = '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]'
            reviews_count_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span//span//span[@aria-label]'
            reviews_average_xpath = '//div[@class="TIHn2 "]//div[@class="fontBodyMedium dmRWX"]//div//span[@aria-hidden]'
            intro_xpath = '//div[@class="WeS02d fontBodyMedium"]//div[@class="PYvSYb "]'
            info1 = '//div[@class="LTs0Rc"][1]'
            info2 = '//div[@class="LTs0Rc"][2]'
            info3 = '//div[@class="LTs0Rc"][3]'
            opens_at_xpath = '//button[contains(@data-item-id, "oh")]//div[contains(@class, "fontBodyMedium")]'
            opens_at_xpath2 = '//div[@class="MkV9"]//span[@class="ZDu9vd"]//span[2]'
            place_type_xpath = '//div[@class="LBgpqf"]//button[@class="DkEaL "]'
            sort_button= '//button/span/span[contains(text(),"Sort")]'
            
            print(args)
            await page.goto(listing_href, timeout=60000)
            
            
            await page.wait_for_timeout(4000)

            try:
                await page.wait_for_selector(name_xpath, timeout=60000)
            except:
                pass
            name = await page.locator(name_xpath).inner_text() if await page.locator(name_xpath).count() > 0 else ""
            
            address = await page.locator(address_xpath).inner_text() if await page.locator(address_xpath).count() > 0 else ""
            
            website = await page.locator(website_xpath).inner_text() if await page.locator(website_xpath).count() > 0 else ""
            
            phone = await page.locator(phone_number_xpath).inner_text() if await page.locator(phone_number_xpath).count() > 0 else ""
            
            place_type = await page.locator(place_type_xpath).inner_text() if await page.locator(place_type_xpath).count() > 0 else ""
            
            introduction = await page.locator(intro_xpath).inner_text() if await page.locator(intro_xpath).count() > 0 else "None Found"

            reviews_count = 0
            if await page.locator(reviews_count_xpath).count() > 0:
                temp = await page.locator(reviews_count_xpath).inner_text()
                temp = temp.replace('(', '').replace(')', '').replace(',', '')
                reviews_count = int(temp)

            reviews_average = 0.0
            if await page.locator(reviews_average_xpath).count() > 0:
                temp = await page.locator(reviews_average_xpath).inner_text()
                temp = temp.replace(' ', '').replace(',', '.')
                reviews_average = float(temp)

            store_shopping = "No"
            in_store_pickup = "No"
            store_delivery = "No"

            if await page.locator(info1).count() > 0:
                temp = await page.locator(info1).inner_text()
                temp = temp.split('·')
                if len(temp) > 1:
                    check = temp[1].replace("\n", "")
                    if 'shop' in check.lower():
                        store_shopping = "Yes"
                    elif 'pickup' in check.lower():
                        in_store_pickup = "Yes"
                    elif 'delivery' in check.lower():
                        store_delivery = "Yes"

            if await page.locator(info2).count() > 0:
                temp = await page.locator(info2).inner_text()
                temp = temp.split('·')
                if len(temp) > 1:
                    check = temp[1].replace("\n", "")
                    if 'pickup' in check.lower():
                        in_store_pickup = "Yes"
                    elif 'shop' in check.lower():
                        store_shopping = "Yes"
                    elif 'delivery' in check.lower():
                        store_delivery = "Yes"

            if await page.locator(info3).count() > 0:
                temp = await page.locator(info3).inner_text()
                temp = temp.split('·')
                if len(temp) > 1:
                    check = temp[1].replace("\n", "")
                    if 'delivery' in check.lower():
                        store_delivery = "Yes"
                    elif 'pickup' in check.lower():
                        in_store_pickup = "Yes"
                    elif 'shop' in check.lower():
                        store_shopping = "Yes"

            opens_at = ""
            if await page.locator(opens_at_xpath).count() > 0:
                opens = await page.locator(opens_at_xpath).inner_text()
                opens = opens.split('⋅')
                if len(opens) != 1:
                    opens = opens[1]
                opens = opens.replace("\u202f", "")
                opens_at = opens
            else:
                if await page.locator(opens_at_xpath2).count() > 0:
                    opens = await page.locator(opens_at_xpath2).inner_text()
                    opens = opens.split('⋅')
                    opens = opens[1]
                    opens = opens.replace("\u202f", "")
                    opens_at = opens

            overview_xpath= '//button[contains(@aria-label,"Overview ")]'
            try:
                await page.wait_for_selector(overview_xpath, timeout=60000)
            except:
                pass
            await page.locator(overview_xpath).click()

            await page.mouse.wheel(0, 10000)
            await asyncio.sleep(1)
            
            await page.mouse.wheel(0, 10000)
            await asyncio.sleep(1)

            iframe = page.frame_locator("//iframe[@class='rvN3ke']")

            map_insta= "N/A"
            map_facebook= "N/A"
            for links_div in await iframe.locator('//div[@role="heading"]/parent::g-card-section/parent::div/parent::div').all():
                async with page.expect_popup() as popup_info:  # Wait for new tab
                    await links_div.click()
                new_tab = await popup_info.value  

                if len(new_tab.url.split("/"))==5:
                    if new_tab.url.startswith("https://www.instagram.com/"):
                        map_insta= new_tab.url
                    if new_tab.url.startswith("https://www.facebook.com/"):
                        map_facebook= new_tab.url
                
                print("Opened URL:", new_tab.url, len(new_tab.url.split("/"))) 

                await new_tab.close() 

            print('insta on map: ',map_insta)

            print('Facebook on map: ',map_facebook)

            negative_reviews= []
            Positive_reviews= []
            
            try:
                await page.wait_for_selector(sort_button, timeout=60000)
            except:
                pass
            await page.locator(sort_button).click()

            await asyncio.sleep(1)
            
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.3)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.3)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            await asyncio.sleep(2)
            
            await page.mouse.wheel(0, 10000)
            await asyncio.sleep(1)

            more_buttons_xpath = '//button[contains(text(), "More")]'
            more_buttons = await page.locator(more_buttons_xpath).all()

            for index, button in enumerate(more_buttons):
                try:
                    if await button.is_visible():  # Click only if the button is visible
                        # print(f"Clicking 'More' button {index + 1}")
                        await button.click(timeout=50000)  # Set a lower timeout
                        await asyncio.sleep(2)  # Let content expand
                except Exception as e:
                    print(f"Error clicking 'More' button {index + 1}: {e}")
            
            # Xpath for reviews
            reviews_xpath = '//div[contains(@class, "MyEned")]/span'  # Adjust based on actual HTML structure
            

            # Extract all reviews
            reviews_locators = await page.locator(reviews_xpath).all()
            reviews = []
            for review_locator in reviews_locators:
                reviews.append(await review_locator.inner_text())

            # Print or store reviews
            unique_reviews= []

            for review_ in reviews:
                if review_ not in unique_reviews:
                    if review_ != " More":
                        unique_reviews.append(review_)

            if len(unique_reviews)>5:
                negative_reviews= unique_reviews[:5]
            else:
                negative_reviews= unique_reviews
            
            
            try:
                await page.wait_for_selector(sort_button, timeout=60000)
            except:
                pass

            await page.locator(sort_button).click()

            await asyncio.sleep(1)
            
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.3)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)
            
            await page.mouse.wheel(0, 10000)
            await asyncio.sleep(1)

            more_buttons = await page.locator(more_buttons_xpath).all()

            for index, button in enumerate(more_buttons):
                try:
                    if await button.is_visible():  # Click only if the button is visible
                        # print(f"Clicking 'More' button {index + 1}")
                        await button.click(timeout=0)  # Set a lower timeout
                        await asyncio.sleep(1)  # Let content expand
                except Exception as e:
                    print(f"Error clicking 'More' button {index + 1}: {e}")
                    
            # Xpath for reviews

            # Extract all reviews
            reviews_locators = await page.locator(reviews_xpath).all()
            reviews = []
            for review_locator in reviews_locators:
                reviews.append(await review_locator.inner_text())

            # Print or store reviews
            unique_reviews= []

            for review_ in reviews:
                if review_ not in unique_reviews:
                    if review_ != " More":
                        unique_reviews.append(review_)

            if len(unique_reviews)>5:
                Positive_reviews= unique_reviews[:5]
            else:
                Positive_reviews= unique_reviews

            if len(negative_reviews) == 0 or len(Positive_reviews) == 0:
                
                await page.locator(sort_button).click()

                await asyncio.sleep(2)
                
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.3)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.3)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.3)
                await page.keyboard.press("Enter")
                await asyncio.sleep(2)
                
                await page.mouse.wheel(0, 10000)
                await asyncio.sleep(1)

                more_buttons = await page.locator(more_buttons_xpath).all()

                for index, button in enumerate(more_buttons):
                    try:
                        if await button.is_visible():  # Click only if the button is visible
                            # print(f"Clicking 'More' button {index + 1}")
                            await button.click(timeout=50000)  # Set a lower timeout
                            await asyncio.sleep(1)  # Let content expand
                    except Exception as e:
                        print(f"Error clicking 'More' button {index + 1}: {e}")
                
                # Xpath for reviews
                

                # Extract all reviews
                reviews_locators = await page.locator(reviews_xpath).all()
                reviews = []
                for review_locator in reviews_locators:
                    reviews.append(await review_locator.inner_text())

                # Print or store reviews
                unique_reviews= []

                for review_ in reviews:
                    if review_ not in unique_reviews:
                        if review_ != " More":
                            unique_reviews.append(review_)

                if len(unique_reviews)>5:
                    negative_reviews= unique_reviews[:5]
                else:
                    negative_reviews= unique_reviews


                try:
                    await page.wait_for_selector(sort_button, timeout=60000)
                except:
                    pass

                await page.locator(sort_button).click()

                await asyncio.sleep(1)
                
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.3)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.3)
                await page.keyboard.press("Enter")
                await asyncio.sleep(1)
                
                await page.mouse.wheel(0, 10000)
                await asyncio.sleep(2)

                more_buttons = await page.locator(more_buttons_xpath).all()

                for index, button in enumerate(more_buttons):
                    try:
                        if await button.is_visible():  # Click only if the button is visible
                            # print(f"Clicking 'More' button {index + 1}")
                            await button.click(timeout=50000)  # Set a lower timeout
                            await asyncio.sleep(1)  # Let content expand
                    except Exception as e:
                        print(f"Error clicking 'More' button {index + 1}: {e}")
                
                # Xpath for reviews
                try:
                    await page.wait_for_selector(reviews_xpath, timeout=60000)
                except:
                    pass

                # Extract all reviews
                reviews_locators = await page.locator(reviews_xpath).all()
                reviews = []
                for review_locator in reviews_locators:
                    reviews.append(await review_locator.inner_text())

                # Print or store reviews
                unique_reviews= []

                for review_ in reviews:
                    if review_ not in unique_reviews:
                        if review_ != " More":
                            unique_reviews.append(review_)

                if len(unique_reviews)>5:
                    Positive_reviews= unique_reviews[:5]
                else:
                    Positive_reviews= unique_reviews

            print("\n\nnegative_reviews:",negative_reviews, "\n\nPositive_reviews:",Positive_reviews)

            atmosphere= []
            try: 
                about_xpath= '//button[contains(@aria-label,"About ")]'
                try:
                    await page.wait_for_selector(about_xpath, timeout=60000)
                except:
                    pass
                await page.locator(about_xpath).click()
                await asyncio.sleep(1)
                atmosphere_xpath= '//h2/parent::div/ul/li/div/span[2]'
                try:
                    await page.wait_for_selector(atmosphere_xpath, timeout=60000)
                except:
                    pass
                atmosphere_elements= await page.locator(atmosphere_xpath).all()
                for atmosphere_element in atmosphere_elements:
                    atmosphere.append(await atmosphere_element.inner_text())
            except:
                pass

            try:
                Positive_review_1= Positive_reviews[0]
            except:
                Positive_review_1= "N/A"
            try:
                Positive_review_2= Positive_reviews[1]
            except:
                Positive_review_2= "N/A"
            try:
                Positive_review_3= Positive_reviews[2]
            except:
                Positive_review_3= "N/A"
            try:
                Positive_review_4= Positive_reviews[3]
            except:
                Positive_review_4= "N/A"
            try:
                Positive_review_5= Positive_reviews[4]
            except:
                Positive_review_5= "N/A"
            try:
                Negative_review_1= negative_reviews[0]
            except:
                Negative_review_1= "N/A"
            try:
                Negative_review_2= negative_reviews[1]
            except:
                Negative_review_2= "N/A"
            try:
                Negative_review_3= negative_reviews[2]
            except:
                Negative_review_3= "N/A"
            try:
                Negative_review_4= negative_reviews[3]
            except:
                Negative_review_4= "N/A"
            try:
                Negative_review_5= negative_reviews[4]
            except:
                Negative_review_5= "N/A"

            listing_data= {
                'Names': name,
                'Website': website,
                'Introduction': introduction,
                'Phone Number': phone,
                'Address': address,
                'Review Count': reviews_count,
                'Average Review Count': reviews_average,
                'Store Shopping': store_shopping,
                'In Store Pickup': in_store_pickup,
                'Delivery': store_delivery,
                'Type': place_type,
                'Opens At': opens_at,
                'Negative Review 1': Negative_review_1,
                'Negative Review 2': Negative_review_2,
                'Negative Review 3': Negative_review_3,
                'Negative Review 4': Negative_review_4,
                'Negative Review 5': Negative_review_5,
                'Positive Review 1': Positive_review_1,
                'Positive Review 2': Positive_review_2,
                'Positive Review 3': Positive_review_3,
                'Positive Review 4': Positive_review_4,
                'Positive Review 5': Positive_review_5,
                'Atmosphere': str(atmosphere)[1:-1],
                'Map Facebook': str(map_facebook),
                'Map Instagram': str(map_insta)
            }

            send_update({"status": "progress", "message": f"Processed listing {idx+1}/{len_listings}: {name}", "total": len_listings, "current": idx+1})
            await page.wait_for_timeout(1000)
            return listing_data
        except Exception as e:
            # if "Timeout" in str(e) and timeout_count<20:
            #     timeout_count= timeout_count+1
            #     return await async_listing_scraper(args, browser)

            exc_type, exc_obj, exc_tb = traceback.sys.exc_info()
            
            # Get file name and line number
            line_no = traceback.extract_tb(exc_tb)[-1][1]

            send_update({"status": "error", "message": f"Error scraping listing: line no: {line_no} {str(e)}"})
            return {
                'Names': "Null",
                'Website': "Null",
                'Introduction': "Null",
                'Phone Number': "Null",
                'Address': "Null",
                'Review Count': 0,
                'Average Review Count': 0.0,
                'Store Shopping': "No",
                'In Store Pickup': "No",
                'Delivery': "No",
                'Type': "Null",
                'Opens At': "Null",
                'Negative Review 1': "Null",
                'Negative Review 2': "Null",
                'Negative Review 3': "Null",
                'Negative Review 4': "Null",
                'Negative Review 5': "Null",
                'Positive Review 1': "Null",
                'Positive Review 2': "Null",
                'Positive Review 3': "Null",
                'Positive Review 4': "Null",
                'Positive Review 5': "Null",
                'Atmosphere': "Null",
                'Map Facebook': "Null",
                'Map Instagram': "Null"
            }
        
    finally:
        await page.close()
        
        
async def run_scraper(search_for, total, api_endpoint=None, api_key=None):
    send_update({"status": "info", "message": f"Starting scraper for '{search_for}' with {total} results"})
    timeout_count = 0
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1920, "height": 1080})

            send_update({"status": "info", "message": "Navigating to Google Maps..."})
            await page.goto("https://www.google.com/maps", timeout=60000)
            await page.wait_for_timeout(3000)

            send_update({"status": "info", "message": f"Searching for '{search_for}'..."})
            
            await page.wait_for_selector('//input[@id="searchboxinput"]', timeout=60000)
            search_box = page.locator('//input[@id="searchboxinput"]')
            await search_box.click()
            await search_box.fill(search_for)
            await page.keyboard.press("Enter")

            await page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]', timeout=60000)
            await page.hover('//a[contains(@href, "https://www.google.com/maps/place")]')

            listings = []
            last_height = 0

            send_update({"status": "info", "message": "Scrolling to find listings..."})
            while len(listings) < total:
                await page.mouse.wheel(0, 10000)
                await page.wait_for_selector('//a[contains(@href, "https://www.google.com/maps/place")]')
                await page.wait_for_timeout(50000)  # Wait for content to load

                new_listings = await page.locator('//a[contains(@href, "https://www.google.com/maps/place")]').all()
                new_listings = [listing.locator("xpath=..") for listing in new_listings]
                if len(new_listings) > len(listings):
                    listings = new_listings
                    send_update({"status": "progress", "message": f"Found {len(listings)} listings", "total": total, "current": len(listings)})
                else:
                    current_height = await page.evaluate("window.scrollY")
                    if current_height == last_height:
                        send_update({"status": "info", "message": f"No new results found, stopping scroll. Found {len(listings)} results."})
                        break
                    last_height = current_height

            listings = listings[:total]

            send_update({"status": "info", "message": "Extracting basic data from listings..."})

            listing_hrefs = []
            for idx, listing in enumerate(listings):
                try:
                    href = await listing.locator('a.hfpxzc').get_attribute('href')
                    if href:
                        listing_hrefs.append(href)
                    else:
                        href = await listing.locator('a[jslog]').get_attribute('href')
                        if href:
                            listing_hrefs.append(href)
                except Exception as e:
                    send_update({"status": "error", "message": f"Error extracting href for listing {idx}: {str(e)}"})


            async def bounded_gather(tasks, limit):
                semaphore = asyncio.Semaphore(limit)
                
                async def bounded_task(task):
                    async with semaphore:
                        return await task
                        
                return await asyncio.gather(*[bounded_task(task) for task in tasks])

            # Usage:
            args_list = [(idx, href, len(listing_hrefs), search_for, timeout_count) 
                        for idx, href in enumerate(listing_hrefs)]

            tasks = [async_listing_scraper(arg, browser) for arg in args_list]
            scraped_data = await bounded_gather(tasks, 10)  # Process 5 at a time
# ``````````````````````````````````````````````````````````````````````````````````````````
            df = pd.DataFrame(scraped_data)
            df = df.drop_duplicates(subset=['Names'], keep='first')
            for column in df.columns:
                if df[column].nunique() == 1:
                    df.drop(column, axis=1, inplace=True)

            send_update({"status": "info", "message": "Extracting detailed website data..."})
            extractor = WebsiteDataExtractor()
            website_data = []

            for i, website in enumerate(df['Website'].tolist()):
                send_update({"status": "progress", "message": f"Processing website {i+1}/{len(df)}", "total": len(df), "current": i+1})
                data = extractor.extract_structured_data(website)
                website_data.append(data)
                # time.sleep(1)

            send_update({"status": "info", "message": "Processing extracted data..."})
            df['Email'] = [data['contact_info']['emails'][0] if data['contact_info']['emails'] else 'N/A' for data in website_data]
            df['Additional_Phones'] = [', '.join(data['contact_info']['phones']) if data['contact_info']['phones'] else 'N/A' for data in website_data]
            df['Facebook'] = [', '.join(data['social_media'].get('facebook', [])) if data['social_media'].get('facebook') else 'N/A' for data in website_data]
            df['Instagram'] = [', '.join(data['social_media'].get('instagram', [])) if data['social_media'].get('instagram') else 'N/A' for data in website_data]
            df['Twitter'] = [', '.join(data['social_media'].get('twitter', [])) if data['social_media'].get('twitter') else 'N/A' for data in website_data]
            df['Linkedin'] = [', '.join(data['social_media'].get('linkedin', [])) if data['social_media'].get('linkedin') else 'N/A' for data in website_data]
            df['Youtube'] = [', '.join(data['social_media'].get('youtube', [])) if data['social_media'].get('youtube') else 'N/A' for data in website_data]
            df['Business_Hours'] = [str(data['business_hours']) if data['business_hours'] else 'N/A' for data in website_data]

            def extract_address_components(address):
                if not address:
                    return None, None, None, None
                parts = address.split(', ')
                street = parts[0] if parts else None
                city = parts[1] if len(parts) > 1 else None
                state = parts[2].split(' ')[0] if len(parts) > 2 else None
                postal_code = parts[2].split(' ')[1] if len(parts) > 2 and len(parts[2].split(' ')) > 1 else None
                return street, city, state, postal_code

            df[['Street', 'City', 'State', 'Postal Code']] = df['Address'].apply(lambda x: pd.Series(extract_address_components(x)))

            send_update({"status": "info", "message": "Extracting Facebook emails..."})
            df['email_1'] = 'N/A'
            df['Facebook Intro'] = 'N/A'

            for index, row in enumerate(df.iterrows()):  # Regular for loop instead of async for
                row = row[1]  # Get the actual row data
                facebook_links = row['Facebook'].split(', ')
                for link in facebook_links:
                    if link != 'N/A':
                        try:
                            send_update({"status": "progress", "message": f"Processing Facebook link {index+1}/{len(df)}", "total": len(df), "current": index+1})
                            temp_page = await browser.new_page()
                            await temp_page.goto(link, timeout=60000)
                            await temp_page.wait_for_timeout(5000)

                            if await temp_page.locator('div[role="dialog"]').count() > 0:
                                try:
                                    close_button = temp_page.locator('div[role="dialog"] button[aria-label="Close"]')
                                    if await close_button.count() > 0:
                                        await close_button.hover()
                                        await close_button.click()
                                        await temp_page.wait_for_timeout(2000)
                                except Exception as popup_error:
                                    send_update({"status": "error", "message": f"Error closing popup on {link}: {popup_error}"})

                            try:
                                facebook_intro = await temp_page.locator('//div[@class="xieb3on"]/div/div/div/span').inner_text()
                                df.at[index, 'Facebook Intro'] = facebook_intro
                            except:
                                df.at[index, 'Facebook Intro'] = "N/A"

                            content = await temp_page.content()
                            try:
                                emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}', content)
                                if emails:
                                    df.at[index, 'email_1'] = emails[0]
                                else:
                                    send_update({"status": "warning", "message": f"No email found on {link}"})
                            except Exception as re_error:
                                send_update({"status": "error", "message": f"Error finding emails on {link}: {re_error}"})

                            await temp_page.close()

                        except Exception as e:
                            send_update({"status": "error", "message": f"Error navigating to {link}: {e}"})            # Add search query column with dynamic values
            if not df.empty:  # Check if DataFrame is not empty
                df['search_query'] = df.apply(
                    lambda row: f"{search_for.split('in')[0].strip()}, {row['Postal Code']}, {row['City']}, {row['State']}, US",
                    axis=1
                )
            else:
                df['search_query'] = "N/A"  # If DataFrame is empty, search_query is "N/A"

            # Email Validation and Cleaning
            def clean_email(email):
                if pd.isna(email) or email == 'N/A':
                    return 'N/A'
                email = email.lower()
                cleaned_email = re.sub(r'[^a-z@.]', '', email)
                return cleaned_email

            df['Email'] = df['Email'].apply(clean_email)
            df['email_1'] = df['email_1'].apply(clean_email)

            send_update({"status": "info", "message": "Saving data to files..."})
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            json_filename = f'detailed_business_data_{timestamp}.json'
            csv_filename = f'business_data_{timestamp}.csv'
            

                        # After you've collected all scraped_data and before saving to JSON, add this code:
            for i, listing in enumerate(scraped_data):
                if i < len(website_data):  # Make sure we don't go out of bounds
                    # Add review data to the website_data
                    website_data[i]['reviews'] = {
                        'negative_reviews': [
                            listing.get('Negative Review 1', 'N/A'),
                            listing.get('Negative Review 2', 'N/A'),
                            listing.get('Negative Review 3', 'N/A'),
                            listing.get('Negative Review 4', 'N/A'),
                            listing.get('Negative Review 5', 'N/A')
                        ],
                        'positive_reviews': [
                            listing.get('Positive Review 1', 'N/A'),
                            listing.get('Positive Review 2', 'N/A'),
                            listing.get('Positive Review 3', 'N/A'),
                            listing.get('Positive Review 4', 'N/A'),
                            listing.get('Positive Review 5', 'N/A')
                        ]
                    }
                    
                    # Add atmosphere data
                    website_data[i]['atmosphere'] = listing.get('Atmosphere', 'N/A')
                    
                    # Add map social media links
                    website_data[i]['map_social_media'] = {
                        'facebook': listing.get('Map Facebook', 'N/A'),
                        'instagram': listing.get('Map Instagram', 'N/A')
                    }
            with open(json_filename, 'w') as f:
                json.dump(website_data, f, indent=2)

            df.to_csv(csv_filename, index=False)
            send_update({"status": "success", "message": f"Data saved to {csv_filename} and {json_filename}", "csv_file": csv_filename, "json_file": json_filename})
            
            # Prepare combined data for API submission
            # This includes both the detailed website data and the DataFrame data
            combined_data = {
                "search_query": search_for,
                "timestamp": timestamp,
                "listings_count": len(df),
                "dataframe_data": json.loads(df.to_json(orient='records')),
                "detailed_website_data": website_data
            }
            with open("API Data_"+json_filename, 'w') as f:
                json.dump(combined_data, f, indent=4)
            
            # Send data to API if endpoint is provided
            if api_endpoint:
                send_update({"status": "info", "message": f"Sending data to API endpoint: {api_endpoint}"})
                if send_to_api(combined_data, api_endpoint, api_key):
                    send_update({"status": "success", "message": "Data successfully sent to API"})
                else:
                    send_update({"status": "error", "message": "Failed to send data to API"})
            else:
                send_update({"status": "warning", "message": "No API endpoint provided. Skipping API submission."})
            
            await browser.close()
            
        except Exception as e:
            exc_type, exc_obj, exc_tb = traceback.sys.exc_info()
            line_no = traceback.extract_tb(exc_tb)[-1][1]
            send_update({"status": "error", "message": f"Scraper error: line no:{line_no} {str(e)}"})
    
    update_queue.put("DONE")
# Third fix: Correct the server startup and scraper launch
def main(search_for=None, total=None, api_endpoint=None, api_key=None):
    # Get values from environment variables if not provided
    port = int(os.getenv('PORT', 5001))
    host = os.getenv('HOST', '0.0.0.0')
    search_for = search_for or os.getenv('DEFAULT_SEARCH_QUERY', 'barber in Berlin')
    total = total or int(os.getenv('DEFAULT_RESULTS_COUNT', 5))
    api_endpoint = api_endpoint or os.getenv('DEFAULT_API_ENDPOINT', '')
    api_key = api_key or os.getenv('DEFAULT_API_KEY', '')
    
    # Use daemon=True to allow application to exit when main thread exits
    # server_thread = threading.Thread(
    #     target=lambda: app.run(
    #         debug=False,  # Set to False in the thread to avoid reloader issues
    #         host=host, 
    #         port=port,
    #         use_reloader=False
    #     ),
    #     daemon=True
    # )
    # server_thread.start()
    def run_server():
        app.run(debug=False, host=host, port=port, use_reloader=False)
    run_server()    
    
    # Print instructions
    print("\n============================================")
    print("Google Maps Scraper with SSE and API Posting")
    print("============================================")
    print(f"Server started on http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    print("Open this URL in your browser to use the interface")
    print("Or run the scraper directly below:")
    print("============================================\n")
    
    # # Wait for user to decide
    # choice = input("Do you want to run the scraper now? (y/n): ")
    # if choice.lower() == 'y':
    #     if not api_endpoint:
    #         api_endpoint = input("Enter API endpoint to send data (leave blank to skip): ").strip()
    #     if api_endpoint and not api_key:
    #         api_key = input("Enter API key (leave blank if not required): ").strip()
        
    #     # Run the scraper directly, not in a thread with asyncio
    #     run_scraper(search_for, total, api_endpoint, api_key)
    # else:
    #     print(f"Please use the web interface at http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    #     # Keep the main thread alive
    #     try:
    #         while True:
    #             time.sleep(1)
    #     except KeyboardInterrupt:
    #         print("Shutting down server...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--search", type=str)
    parser.add_argument("-t", "--total", type=int)
    parser.add_argument("-a", "--api", type=str, help="API endpoint to send data")
    parser.add_argument("-k", "--key", type=str, help="API key for authentication")
    args = parser.parse_args()

    search_for = args.search  # Command line args take precedence
    total = args.total
    api_endpoint = args.api
    api_key = args.key

    main(search_for, total, api_endpoint, api_key)