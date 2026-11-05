# =============== MOVIE EXTRACTION ===============

def extract_showtimes(driver):

    results = {
        key: {
            "found": False,
            "showtimes": {}
        }
        for key in TARGETS
    }

    articles = driver.find_elements(
        By.CSS_SELECTOR,
        "article.movie-compare"
    )

    log.info(
        "Movie containers found: %s",
        len(articles)
    )

    for article in articles:
        try:
            titles = article.find_elements(
                By.CSS_SELECTOR, "h2"
            )

            if not titles:
                continue

            movie_title = titles[0].text.strip()
            normalized_title = normalize(movie_title)
            
            # طباعة اسم كل فيلم يتم العثور عليه في الصفحة لكي نراه في الـ Logs
            log.info("Found on page -> Movie: '%s'", movie_title)

            matched_key = None

            for key, target in TARGETS.items():
                if any(
                    phrase in normalized_title
                    for phrase in target["match"]
                ):
                    matched_key = key
                    break

            if not matched_key:
                continue

            results[matched_key]["found"] = True

            log.info(
                "MATCHED Target movie: %s",
                movie_title
            )

            groups = article.find_elements(
                By.CSS_SELECTOR,
                "div.dates ol.showtimes > li"
            )

            for group in groups:
                try:
                    strong = group.find_elements(
                        By.TAG_NAME, "strong"
                    )

                    hall = (
                        strong[0].text.strip()
                        if strong
                        else "Unknown Hall"
                    )

                    items = group.find_elements(
                        By.CSS_SELECTOR, "ol > li"
                    )

                    for item in items:
                        try:
                            links = item.find_elements(
                                By.CSS_SELECTOR,
                                "a.showtime"
                            )

                            if not links:
                                continue

                            link = links[0]
                            show_text = link.text.strip()

                            match = TIME_PATTERN.search(
                                show_text
                            )

                            if not match:
                                continue

                            showtime = normalize_time(
                                match.group(0)
                            )

                            href = link.get_attribute(
                                "href"
                            )

                            booking_url = urljoin(
                                BASE_URL, href
                            ) if href else BASE_URL

                            movie_name = TARGETS[
                                matched_key
                            ]["name"]

                            item_id = make_id(
                                movie_name,
                                hall,
                                showtime,
                                booking_url
                            )

                            results[matched_key][
                                "showtimes"
                            ][item_id] = {
                                "movie": movie_name,
                                "hall": hall,
                                "time": showtime,
                                "link": booking_url
                            }

                        except StaleElementReferenceException:
                            continue

                except StaleElementReferenceException:
                    continue

        except StaleElementReferenceException:
            continue

    for key in TARGETS:
        log.info(
            "%s: %s showtime(s) found",
            TARGETS[key]["name"],
            len(results[key]["showtimes"])
        )

    return results
    
