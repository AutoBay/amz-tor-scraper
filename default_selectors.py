from typing import Dict, Any

DEFAULT_SELECTORS: Dict[str, Any] = {
    "navbar": {
        "search_result_input": "#twotabsearchtextbox",
        "search_button": "#nav-search-submit-button",
        "zipcode": {
            "open_zipcode": "#nav-global-location-popover-link",
            "zipcode_input": "#GLUXZipUpdateInput",
            "apply_button": "#GLUXZipUpdate-announce",
            "done_button": "#a-autoid-51-announce",
        },
    },
    "page_result_products": {
        "product_container": ".a-section.a-spacing-base.desktop-grid-content-view",
        "price": '[data-a-size="xl"]',
        "is_coupon_exist": ".a-size-base.s-highlighted-text-padding.s-coupon-highlight-color.aok-inline-block",
        "product_link_to_extra_data": "a.a-link-normal.s-no-outline",
        "title": "h2.a-size-base-plus.a-spacing-none.a-color-base.a-text-normal",
        "is_limited_time_deal": 'span[data-a-badge-color="sx-red-mvt"]',
    },
    "product_page": {
        "title": "#productTitle, h1#title",
        "images": "#canvasCaption",
        "seller_name": "#sellerProfileTriggerId",
        "description": "#feature-bullets",
        "is_on_stock": "#availability",
        "return_policy": "#returnsInfoFeature_feature_div > div.offer-display-feature-text.a-size-small > span > a > span",

        # Tech-spec tables (existing)
        "details_table_rows": (
            "#productDetails_techSpec_section_1 tr, "
            "#productDetails_detailBullets_sections1 tr, "
            "#productDetails_techSpec_section_2 tr, "
            "table.prodDetTable tr"
        ),
        "details_th": "th, td.prodDetSectionEntry",
        "details_td": "td, td.prodDetAttrValue",

        # Detail bullets block (added; matches the HTML you pasted)
        "detail_bullets_rows": "#detailBullets_feature_div ul.detail-bullet-list > li",
        "detail_bullets_key": "span.a-list-item > span.a-text-bold",
        "detail_bullets_val": "span.a-list-item > span:not(.a-text-bold)",

        "is_more_deals_on_releated_products": "#sp_detail_thematic-hercules_hybrid_deals_T1",
        "stock_positive_keywords": "in stock|available|ships soon",

        # Pricing selectors
        "price_current": "#corePrice_feature_div .a-price .a-offscreen, #price_inside_buybox, #tp_price_block_total_price_ww",
        "price_original": "#price .a-text-price .a-offscreen, #corePrice_desktop .a-text-price .a-offscreen, #listPriceLegalMessage .a-offscreen",
        "coupon_text": "#couponBadgeRegularArithmetic, #couponTextBucket, #promoPriceBlockMessage_feature_div",
        "limited_deal_badge": "span[data-a-badge-color='sx-red-mvt'], #dealBadge_feature_div, #priceBadging_feature_div",
    },
}
