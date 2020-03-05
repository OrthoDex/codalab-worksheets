import argparse
import os
import random
import string
import time

from abc import ABC, abstractmethod
from diffimg import diff
from selenium import webdriver
from selenium.webdriver import ChromeOptions, FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait


class UITester(ABC):
    # This image diff threshold is set to an upper bound of 10% for now. We should try our best
    # to at least maintain this upper bound.
    _SCREENSHOT_DIFF_THRESHOLD_PERCENT = 10

    _BASE_PATH = os.path.dirname(os.path.abspath(__file__))
    _DEFAULT_USERNAME = os.getenv('CODALAB_USERNAME', 'codalab')
    _DEFAULT_PASSWORD = os.getenv('CODALAB_PASSWORD', 'codalab')

    def __init__(self, test_name, base_url='http://localhost'):
        self._test_name = test_name
        self._base_url = base_url

    @abstractmethod
    def test(self):
        pass

    def run(self):
        def add_headless(browser_options):
            if args.headless:
                browser_options.add_argument('--headless')

        # Test Firefox
        options = FirefoxOptions()
        add_headless(options)
        self._driver = webdriver.Firefox(log_path='', firefox_options=options)
        self.test()
        self._driver.close()

        # Test Chrome
        options = ChromeOptions()
        add_headless(options)
        self._driver = webdriver.Chrome(chrome_options=options)
        self.test()
        self._driver.close()

    def login(self, username='codalab', password='codalab'):
        self._driver.get(self.get_url('/home'))
        self.click(By.LINK_TEXT, 'LOGIN')
        self.fill_field(By.ID, 'id_login', username)
        self.fill_field(By.ID, 'id_password', password, press_enter=True)

    def add_run_to_worksheet(self, command):
        self.click(By.CSS_SELECTOR, '[aria-label="Add New Run"]')
        self.pause()
        self.scroll_to_bottom('worksheet_container')
        self._driver.switch_to.active_element.send_keys(command)
        self.click(By.XPATH, "//span[.='Confirm']")
        self.longer_pause()

    def rerun_last_bundle(self):
        self.expand_last_bundle()
        self.pause()
        self.scroll_to_bottom('worksheet_container')
        self.click(By.XPATH, "//span[.='Edit and Rerun']")
        self.pause()
        self.scroll_to_bottom('worksheet_container')
        self.click(By.XPATH, "//span[.='Confirm']")
        self.longer_pause()

    def edit_last_bundle_metadata(self, name, description, permission):
        def edit_field(field, text):
            field.click()
            self._driver.switch_to.active_element.send_keys(text)
            self._driver.switch_to.active_element.send_keys(Keys.ENTER)

        # Edit name and description
        self.expand_last_bundle()
        self.pause()
        editable_fields = self._get_partial_matched_elements('class', 'editable-field')
        edit_field(editable_fields[-2], name)
        edit_field(editable_fields[-1], description)

        # Edit bundle permission
        self.scroll_to_bottom('worksheet_container')
        self._get_partial_matched_elements('class', 'MuiSvgIcon-root')[-1].click()
        select_boxes = self._get_partial_matched_elements('class', 'MuiNativeSelect-select')
        self.select_option(select_boxes[-1], permission)

    def expand_last_bundle(self):
        self.pause()
        self.scroll_to_bottom('worksheet_container')
        last_bundle_row = self._get_partial_matched_elements('class', 'BundleRow-withCheckBox')[-1]
        last_bundle_row.find_element(By.CSS_SELECTOR, 'button').click()

    def add_text_to_worksheet(self, text):
        self.click(By.CSS_SELECTOR, '[aria-label="Add Text"]')
        self.pause()
        self.scroll_to_bottom('worksheet_container')
        self.pause()
        self.fill_field(
            By.XPATH, self.constructPartialSelector('class', 'MuiInputBase-input'), text
        )
        self.click(By.XPATH, "//span[.='Save']")
        self.pause()

    def pause(self):
        time.sleep(1)

    def longer_pause(self):
        time.sleep(3)

    def click(self, by, selector):
        self._driver.find_element(by, selector).click()

    def fill_field(self, by, selector, text, press_enter=False):
        textbox = self._driver.find_element(by, selector)
        textbox.send_keys(text)
        if press_enter:
            textbox.send_keys(Keys.ENTER)

    def wait_until_worksheet_content_loads(self):
        self.wait_until_page_loads('ws-item')

    def wait_until_page_loads(self, selector, by=By.CLASS_NAME):
        timeout_message = 'Timed out while waiting for {}: {}.'.format(by, selector)
        return WebDriverWait(self._driver, 15).until(
            EC.presence_of_element_located((by, selector)), message=timeout_message
        )

    def switch_to_new_tab(self):
        # Just give enough time for the new tab to get opened
        self.pause()
        self._driver.switch_to.window(
            self._driver.window_handles[len(self._driver.window_handles) - 1]
        )

    def select_option(self, element, to_select):
        for option in element.find_elements_by_tag_name('option'):
            if option.text in to_select:
                option.click()
                break

    def constructPartialSelector(self, by, partial_selector):
        return '//*[contains(@{}, "{}")]'.format(by, partial_selector)

    def output_images(self, selector, num_of_screenshots=10):
        output_dir = self._get_output_dir('out')
        element = "document.getElementById('{}')".format(selector)
        scroll_height = float(self._driver.execute_script('return {}.scrollHeight'.format(element)))
        for i in range(num_of_screenshots):
            y = (i / num_of_screenshots) * scroll_height
            self._driver.execute_script('{}.scrollTo(0, {})'.format(element, y))
            path = os.path.join(output_dir, '{}{}.png'.format(self._test_name, i + 1))
            self._driver.save_screenshot(path)

    def compare_to_baselines(self, num_of_screenshots=10):
        out_dir = self._get_output_dir('out')
        baselines_dir = self._get_output_dir('baselines')
        diff_dir = self._get_output_dir('diff')
        has_failed = False
        for i in range(num_of_screenshots):
            screenshot_filename = '{}{}.png'.format(self._test_name, i + 1)
            out_img = os.path.join(out_dir, screenshot_filename)
            baseline_img = os.path.join(baselines_dir, screenshot_filename)
            diff_img = os.path.join(diff_dir, screenshot_filename)
            diff_percent = (
                diff(baseline_img, out_img, delete_diff_file=True, ignore_alpha=True) * 100
            )
            print(
                '{}% difference in {} for {}'.format(
                    diff_percent, self._get_browser(), screenshot_filename
                )
            )

            if diff_percent > UITester._SCREENSHOT_DIFF_THRESHOLD_PERCENT:
                # If an image comparison has failed, generate diff and print an error message in red
                has_failed = True
                diff(
                    out_img,
                    baseline_img,
                    delete_diff_file=False,
                    diff_img_file=diff_img,
                    ignore_alpha=True,
                )
                print(
                    '\033[91mScreenshot comparison failed in {} for {} by {}%\033[0m'.format(
                        self._get_browser(), screenshot_filename, diff_percent
                    )
                )

        assert not has_failed

    def get_url(self, path):
        return '{}/{}'.format(self._base_url, path)

    def make_name_unique(self, name):
        # Appends some unique identifier to the string input
        random_id = ''.join(
            random.choice(string.ascii_lowercase + string.digits) for _ in range(16)
        )
        return name + random_id

    def scroll_to_bottom(self, selector):
        element = "document.getElementById('{}')".format(selector)
        scroll_height = float(self._driver.execute_script('return {}.scrollHeight'.format(element)))
        self._driver.execute_script('{}.scrollTo(0, {})'.format(element, scroll_height))

    def _get_partial_matched_elements(self, by, selector):
        return self._driver.find_elements(By.XPATH, self.constructPartialSelector(by, selector))

    def _get_output_dir(self, folder_name):
        def create_path(path):
            if not os.path.isdir(path):
                os.mkdir(path)

        output_dir = os.path.join(UITester._BASE_PATH, folder_name)
        create_path(output_dir)
        output_dir = os.path.join(output_dir, self._test_name)
        create_path(output_dir)
        output_dir = os.path.join(output_dir, self._get_browser())
        create_path(output_dir)
        return output_dir

    def _get_browser(self):
        return self._driver.capabilities['browserName']


class WorksheetTest(UITester):
    def __init__(self):
        super().__init__('worksheet')

    def test(self):
        self.login()
        self.wait_until_worksheet_content_loads()
        self.click(By.LINK_TEXT, 'Small Worksheet [cl_small_worksheet]')
        self.switch_to_new_tab()
        self.wait_until_worksheet_content_loads()
        self.output_images('worksheet_container')
        self.compare_to_baselines()


class EditWorksheetTest(UITester):
    def __init__(self):
        super().__init__('edit_worksheet')

    def test(self):
        self.login()
        self.wait_until_worksheet_content_loads()

        # Create a new worksheet
        self.click(By.XPATH, '//*[@title="New Worksheet"]')
        self.fill_field(By.ID, 'name', self.make_name_unique('test-worksheet'))
        self._driver.find_element(By.XPATH, "//span[.='Confirm']").find_element(
            By.XPATH, './..'
        ).click()
        self.longer_pause()

        # Add a title to the worksheet
        self.click(By.CLASS_NAME, 'editable-field')
        self._driver.switch_to.active_element.send_keys(
            'Some Random Title for the UI Test Edit Worksheet in CodaLab'
        )
        self._driver.switch_to.active_element.send_keys(Keys.ENTER)

        # Add text to the new worksheet
        self.add_text_to_worksheet('This is some text. ' * 25)
        self.add_text_to_worksheet('This is some more text. ' * 25)

        # Add some bundles and rerun the last bundle
        self.add_run_to_worksheet('echo hello')
        self.add_run_to_worksheet('ls')
        self.add_run_to_worksheet('date')
        self.rerun_last_bundle()

        # Edit metadata of the last bundle
        self.edit_last_bundle_metadata(
            'New Name Given to this Bundle', 'New Description given to this bundle. ' * 5, 'none'
        )

        # Refresh the page to ensure that new changes are persisted
        self._driver.refresh()
        self.wait_until_worksheet_content_loads()
        self.expand_last_bundle()

        # Take screenshots and compare to the existing baseline images
        num_of_screenshots = 2
        self.output_images('worksheet_container', num_of_screenshots)
        self.compare_to_baselines(num_of_screenshots)


def main():
    # Register UI tests here to run them
    all_tests = [WorksheetTest(), EditWorksheetTest()]

    start_time = time.time()
    for test in all_tests:
        test.run()
    duration_seconds = time.time() - start_time
    print('Success.')
    print('\n--- Completion Time: {} minutes---'.format(duration_seconds / 60))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run frontend automation tests for the CodaLab UI')
    parser.add_argument(
        '--headless', action='store_true', help='Whether to test using headless browsers'
    )
    args = parser.parse_args()
    main()
