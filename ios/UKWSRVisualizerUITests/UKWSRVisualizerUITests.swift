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
        XCTAssertTrue(element("StatusStrip").waitForExistence(timeout: 30))

        let loading = element("LaunchLoadingView")
        if loading.exists {
            XCTAssertTrue(loading.waitForNonExistence(timeout: 120), "Launch loading view did not finish.")
        }

        XCTAssertTrue(element("PPIPlotView").waitForExistence(timeout: 15))

        let catalogButton = app.buttons["CatalogItemButton"]
        XCTAssertTrue(catalogButton.waitForExistence(timeout: 60), "Catalog item button did not appear.")
        XCTAssertTrue(waitForElementEnabled(catalogButton, timeout: 60), "Catalog item button stayed disabled.")

        XCTAssertTrue(app.staticTexts["Radar Controls"].exists)
        XCTAssertTrue(app.staticTexts["Display"].exists)
        XCTAssertTrue(app.staticTexts["Metadata"].exists)

        catalogButton.tap()

        XCTAssertTrue(app.navigationBars["Catalog Search"].waitForExistence(timeout: 15))
        let catalogList = element("CatalogSearchList")
        XCTAssertTrue(catalogList.waitForExistence(timeout: 15))
        XCTAssertTrue(app.textFields["CatalogStartDateField"].exists)
        XCTAssertTrue(app.textFields["CatalogEndDateField"].exists)
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "coverage")).firstMatch.waitForExistence(timeout: 20))

        let rows = catalogList.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "CatalogSearchRow-"))
        if !rows.firstMatch.waitForExistence(timeout: 5) {
            catalogList.swipeUp()
        }
        XCTAssertTrue(rows.firstMatch.waitForExistence(timeout: 30), "Catalog search did not show any rows.")

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

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }
}
