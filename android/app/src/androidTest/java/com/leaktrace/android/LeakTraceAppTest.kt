package com.leaktrace.android

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LeakTraceAppTest {

    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    private fun string(id: Int): String = composeRule.activity.getString(id)

    @Test
    fun homeScreenShowsBranding() {
        composeRule.onAllNodesWithText(string(R.string.app_name)).onFirst().assertIsDisplayed()
        composeRule.onNodeWithText(string(R.string.home_tagline)).assertIsDisplayed()
    }

    @Test
    fun aboutScreenOpensAndNavigatesBack() {
        composeRule.onNodeWithText(string(R.string.home_open_about)).performClick()
        composeRule.onNodeWithText(string(R.string.about_title)).assertIsDisplayed()

        composeRule.onNodeWithContentDescription(string(R.string.navigate_back)).performClick()
        composeRule.onNodeWithText(string(R.string.home_tagline)).assertIsDisplayed()
    }
}
