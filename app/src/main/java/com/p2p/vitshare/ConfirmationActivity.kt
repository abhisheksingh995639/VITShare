package com.p2p.vitshare

import android.content.Intent
import androidx.appcompat.app.AppCompatActivity
import android.os.Bundle
import android.widget.Button
import android.widget.TextView

class ConfirmationActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_confirmation)

        supportActionBar?.hide()

        val messageTextView: TextView = findViewById(R.id.messageTextView)
        val acceptButton: Button = findViewById(R.id.acceptButton)
        val rejectButton: Button = findViewById(R.id.rejectButton)

        val fileName = intent.getStringExtra("FILE_NAME") ?: "unknown file"
        val senderName = intent.getStringExtra("SENDER_NAME") ?: "An unknown peer"
        val transferId = intent.getStringExtra("TRANSFER_ID")
        // Get the full metadata JSON string
        val metadataJson = intent.getStringExtra("METADATA_JSON")

        messageTextView.text = "$senderName wants to send you:\n\n$fileName\n\nDo you want to accept?"

        acceptButton.setOnClickListener {
            respondToTransfer(transferId, true, metadataJson)
        }

        rejectButton.setOnClickListener {
            respondToTransfer(transferId, false, metadataJson)
        }
    }

    private fun respondToTransfer(transferId: String?, accepted: Boolean, metadataJson: String?) {
        if (transferId == null || metadataJson == null) {
            finish()
            return
        }
        val responseIntent = Intent(this, NetworkService::class.java).apply {
            action = NetworkService.ACTION_TRANSFER_RESPONSE
            putExtra(NetworkService.EXTRA_TRANSFER_ID, transferId)
            putExtra(NetworkService.EXTRA_TRANSFER_ACCEPTED, accepted)
            // Pass the metadata back to the service
            putExtra(NetworkService.EXTRA_METADATA_JSON, metadataJson)
        }
        startService(responseIntent)
        finish()
    }
}