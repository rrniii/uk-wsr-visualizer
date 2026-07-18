import XCTest
import UIKit

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

        if UIDevice.current.userInterfaceIdiom == .pad {
            XCTAssertTrue(element("IPadRadarWorkspace").waitForExistence(timeout: 30))
        } else {
            XCTAssertTrue(app.navigationBars["UK WSR"].waitForExistence(timeout: 30))
        }
        XCTAssertTrue(element("ScanHeaderBar").waitForExistence(timeout: 30))

        let loading = element("LaunchLoadingView")
        if loading.exists {
            XCTAssertTrue(loading.waitForNonExistence(timeout: 120), "Launch loading view did not finish.")
        }

        XCTAssertTrue(element("PPIPlotView").waitForExistence(timeout: 15))

        if UIDevice.current.userInterfaceIdiom == .pad {
            XCTAssertTrue(element("IPadControlsSidebar").waitForExistence(timeout: 15))
        }

        let catalogButton = app.buttons["CatalogItemButton"]
        XCTAssertTrue(catalogButton.waitForExistence(timeout: 60), "Catalog item button did not appear.")
        XCTAssertTrue(waitForElementEnabled(catalogButton, timeout: 60), "Catalog item button stayed disabled.")

        XCTAssertTrue(app.staticTexts["Radar"].exists)

        catalogButton.tap()

        XCTAssertTrue(app.navigationBars["Select Data"].waitForExistence(timeout: 15))
        let catalogList = element("CatalogSearchList")
        XCTAssertTrue(catalogList.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Search"].exists)
        XCTAssertTrue(element("CatalogEraPicker").exists)
        XCTAssertTrue(app.staticTexts["Shortcuts"].exists)
        XCTAssertTrue(app.textFields["CatalogSearchTextField"].exists)
        let startDateField = app.textFields["CatalogStartField"]
        XCTAssertTrue(scroll(catalogList, until: startDateField, attempts: 3))
        XCTAssertTrue(app.textFields["CatalogEndField"].exists)
        let coverageText = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "coverage")).firstMatch
        XCTAssertTrue(scroll(catalogList, until: coverageText, attempts: 3))

        let rows = catalogList.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "CatalogSearchRow-"))
        if !rows.firstMatch.waitForExistence(timeout: 5) {
            catalogList.swipeUp()
        }
        XCTAssertTrue(rows.firstMatch.waitForExistence(timeout: 30), "Catalog search did not show any rows.")

        app.buttons["CatalogSearchDoneButton"].tap()
        if UIDevice.current.userInterfaceIdiom == .pad {
            XCTAssertTrue(element("IPadRadarWorkspace").waitForExistence(timeout: 15))
        } else {
            XCTAssertTrue(app.navigationBars["UK WSR"].waitForExistence(timeout: 15))
        }
    }

    func testIPadWorkspaceModesExposeComparisonAndProjects() throws {
        app.launch()
        app.tap()

        guard UIDevice.current.userInterfaceIdiom == .pad else { return }
        XCTAssertTrue(element("IPadWorkspaceModePicker").waitForExistence(timeout: 30))

        let compare = app.buttons["Compare"]
        XCTAssertTrue(compare.waitForExistence(timeout: 10))
        compare.tap()
        XCTAssertTrue(element("FourPanelComparisonWorkspace").waitForExistence(timeout: 30))
        XCTAssertTrue(app.staticTexts["Four-panel comparison"].exists)
        XCTAssertGreaterThanOrEqual(app.buttons.matching(NSPredicate(format: "label == %@", "Variable")).count, 4)

        let projects = app.buttons["Projects"]
        XCTAssertTrue(projects.waitForExistence(timeout: 10))
        projects.tap()
        XCTAssertTrue(app.navigationBars["Projects & Provenance"].waitForExistence(timeout: 15))
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

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }
}
