import XCTest

final class UKWSRVisualizerUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false

        app = XCUIApplication()
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_GB", "-UKWSRUITesting"]

        addUIInterruptionMonitor(withDescription: "Location Permission") { alert in
            for title in ["Allow Once", "Allow While Using App", "Allow", "OK"] {
                let button = alert.buttons[title]
                if button.exists {
                    button.tap()
                    return true
                }
            }
            return false
        }
    }

    func testLaunchShellAndCatalogSearchSmokeFlow() throws {
        app.launch()
        app.tap()

        XCTAssertTrue(app.navigationBars["UK WSR"].waitForExistence(timeout: 30))
        XCTAssertTrue(element("ScanHeaderBar").waitForExistence(timeout: 30))

        let loading = element("LaunchLoadingView")
        if loading.exists {
            XCTAssertTrue(loading.waitForNonExistence(timeout: 120), "Launch loading view did not finish.")
        }

        XCTAssertTrue(element("PPIPlotView").waitForExistence(timeout: 15))

        let catalogButton = app.buttons["CatalogItemButton"]
        XCTAssertTrue(catalogButton.waitForExistence(timeout: 60), "Catalog item button did not appear.")
        XCTAssertTrue(waitForElementEnabled(catalogButton, timeout: 60), "Catalog item button stayed disabled.")

        let controls = element("ControlsScrollView")
        XCTAssertTrue(controls.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Radar"].exists)
        XCTAssertTrue(scroll(controls, until: app.staticTexts["Display"], attempts: 4))
        XCTAssertTrue(scroll(controls, until: app.staticTexts["Metadata"], attempts: 6))
        XCTAssertTrue(scrollToTop(controls, until: catalogButton, attempts: 10))

        catalogButton.tap()

        XCTAssertTrue(app.navigationBars["Select Data"].waitForExistence(timeout: 15))
        let catalogList = element("CatalogSearchList")
        XCTAssertTrue(catalogList.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Search"].exists)
        XCTAssertTrue(app.staticTexts["Shortcuts"].exists)
        XCTAssertTrue(app.textFields["CatalogSearchTextField"].exists)
        let startDateField = element("CatalogStartField")
        XCTAssertTrue(scrollSlowly(catalogList, until: startDateField, attempts: 6))
        XCTAssertTrue(element("CatalogEndField").exists)
        let coverageText = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "coverage")).firstMatch
        XCTAssertTrue(scrollSlowly(catalogList, until: coverageText, attempts: 6))

        let rows = catalogList.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "CatalogSearchRow-"))
        XCTAssertTrue(
            scroll(catalogList, until: rows.firstMatch, attempts: 5),
            "Catalog search did not show any rows."
        )

        app.buttons["CatalogSearchDoneButton"].tap()
        XCTAssertTrue(app.navigationBars["UK WSR"].waitForExistence(timeout: 15))
    }

    private func waitForElementEnabled(_ element: XCUIElement, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.exists && element.isEnabled {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        return element.exists && element.isEnabled
    }

    private func scroll(_ container: XCUIElement, until element: XCUIElement, attempts: Int) -> Bool {
        if element.exists {
            return true
        }
        for _ in 0..<attempts {
            container.swipeUp()
            if element.waitForExistence(timeout: 3) {
                return true
            }
        }
        return element.exists
    }

    private func scrollToTop(_ container: XCUIElement, until element: XCUIElement, attempts: Int) -> Bool {
        if element.exists {
            return true
        }
        for _ in 0..<attempts {
            container.swipeDown()
            if element.waitForExistence(timeout: 3) {
                return true
            }
        }
        return element.exists
    }

    private func scrollSlowly(_ container: XCUIElement, until element: XCUIElement, attempts: Int) -> Bool {
        if element.exists {
            return true
        }
        for _ in 0..<attempts {
            let start = container.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.72))
            let end = container.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.48))
            start.press(forDuration: 0.05, thenDragTo: end)
            if element.waitForExistence(timeout: 2) {
                return true
            }
        }
        return element.exists
    }

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }
}
