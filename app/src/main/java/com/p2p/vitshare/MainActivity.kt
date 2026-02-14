package com.p2p.vitshare

import android.app.Dialog
import android.content.*
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import android.view.View
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.graphics.createBitmap
import androidx.core.graphics.set
import androidx.core.net.toUri
import androidx.documentfile.provider.DocumentFile
import androidx.lifecycle.lifecycleScope
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.appbar.MaterialToolbar
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class MainActivity : AppCompatActivity() {

    // UI Elements
    private lateinit var peersRecyclerView: RecyclerView
    private lateinit var filesRecyclerView: RecyclerView
    private lateinit var addFileButton: ImageButton
    private lateinit var addFolderButton: ImageButton
    private lateinit var sendButton: ImageButton
    private lateinit var scanQrButton: ImageButton
    private lateinit var showMyQrButton: ImageButton
    private lateinit var progressLayout: LinearLayout
    private lateinit var progressStatusText: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var toolbar: MaterialToolbar

    // Data & Adapters
    private val discoveredPeers = mutableMapOf<String, String>() // Nickname -> IP
    private val peerNicknames = mutableListOf<String>()
    private lateinit var peersAdapter: SimpleListAdapter

    private val sharableFileNames = mutableListOf<String>()
    private val sharableFileUris = mutableListOf<Uri>()
    private lateinit var filesAdapter: SimpleListAdapter

    // Broadcast Receiver
    private val transferUpdateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                NetworkService.ACTION_PEER_DISCOVERED -> {
                    val nickname = intent.getStringExtra(NetworkService.EXTRA_PEER_NICKNAME)
                    val ip = intent.getStringExtra(NetworkService.EXTRA_PEER_IP)
                    if (nickname != null && ip != null && !discoveredPeers.containsKey(nickname)) {
                        discoveredPeers[nickname] = ip
                        val insertionPoint = peerNicknames.binarySearch(nickname).let { if (it < 0) -(it + 1) else it }
                        peerNicknames.add(insertionPoint, nickname)
                        peersAdapter.notifyItemInserted(insertionPoint)

                        peersRecyclerView.scrollToPosition(insertionPoint)
                        peersAdapter.setSelectedPosition(insertionPoint)

                        Toast.makeText(this@MainActivity, "$nickname connected!", Toast.LENGTH_SHORT).show()
                    }
                }
                NetworkService.ACTION_TRANSFER_UPDATE -> handleProgressUpdate(intent)
            }
        }
    }

    // Activity Result Launchers
    private val qrCodeScannerLauncher = registerForActivityResult(ScanContract()) { result ->
        if (result.contents != null) {
            val ipAddress = result.contents
            val intent = Intent(this, NetworkService::class.java).apply {
                action = "com.p2p.vitshare.INITIATE_QR_HANDSHAKE"
                putExtra(NetworkService.EXTRA_TARGET_IP, ipAddress)
            }
            startService(intent)
        }
    }

    private val filePickerLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        uri?.let {
            sharableFileUris.add(it)
            sharableFileNames.add(getFileName(it))
            filesAdapter.notifyItemInserted(sharableFileNames.size - 1)
        }
    }

    private val folderPickerLauncher = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri: Uri? ->
        uri?.let { folderUri ->
            Toast.makeText(this, "Zipping folder... please wait", Toast.LENGTH_SHORT).show()
            lifecycleScope.launch(Dispatchers.IO) {
                val zippedFileUri = zipDirectory(folderUri)
                withContext(Dispatchers.Main) {
                    if (zippedFileUri != null) {
                        sharableFileUris.add(zippedFileUri)
                        sharableFileNames.add(getFileName(zippedFileUri))
                        filesAdapter.notifyItemInserted(sharableFileNames.size - 1)
                        Toast.makeText(applicationContext, "Folder added!", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(applicationContext, "Failed to zip folder.", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Initialize Views
        toolbar = findViewById(R.id.toolbar)
        peersRecyclerView = findViewById(R.id.peersRecyclerView)
        filesRecyclerView = findViewById(R.id.filesRecyclerView)
        addFileButton = findViewById(R.id.addFileButton)
        addFolderButton = findViewById(R.id.addFolderButton)
        sendButton = findViewById(R.id.sendButton)
        scanQrButton = findViewById(R.id.scanQrButton)
        showMyQrButton = findViewById(R.id.showMyQrButton)
        progressLayout = findViewById(R.id.progressLayout)
        progressStatusText = findViewById(R.id.progressStatusText)
        progressBar = findViewById(R.id.progressBar)

        setupRecyclerViews()

        // Setup Button Listeners
        addFileButton.setOnClickListener { filePickerLauncher.launch("*/*") }
        addFolderButton.setOnClickListener { folderPickerLauncher.launch(null) }
        sendButton.setOnClickListener { sendSelectedFiles() }
        scanQrButton.setOnClickListener {
            val options = ScanOptions().apply {
                setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                setPrompt("Scan a VIT Share QR Code")
                setBeepEnabled(true)
                setOrientationLocked(true)
            }
            qrCodeScannerLauncher.launch(options)
        }
        showMyQrButton.setOnClickListener {
            showQrCodeDialog()
        }

        // Register Receiver & Start Service
        val filter = IntentFilter().apply {
            addAction(NetworkService.ACTION_PEER_DISCOVERED)
            addAction(NetworkService.ACTION_TRANSFER_UPDATE)
        }
        LocalBroadcastManager.getInstance(this).registerReceiver(transferUpdateReceiver, filter)
        startService(Intent(this, NetworkService::class.java))
    }

    private fun setupRecyclerViews() {
        peersAdapter = SimpleListAdapter(peerNicknames) { /* Click handled by adapter */ }
        peersRecyclerView.adapter = peersAdapter
        peersRecyclerView.layoutManager = LinearLayoutManager(this)

        filesAdapter = SimpleListAdapter(sharableFileNames) { /* Click handled by adapter */ }
        filesRecyclerView.adapter = filesAdapter
        filesRecyclerView.layoutManager = LinearLayoutManager(this)
    }

    private fun sendSelectedFiles() {
        val selectedPeerPositions = peersAdapter.selectedPositions
        val selectedFilePositions = filesAdapter.selectedPositions

        if (selectedPeerPositions.isEmpty() || selectedFilePositions.isEmpty()) {
            Toast.makeText(this, "Please select at least one peer and one item", Toast.LENGTH_SHORT).show()
            return
        }

        val selectedTargetIps = selectedPeerPositions.mapNotNull { discoveredPeers[peerNicknames[it]] }
        val selectedUris = selectedFilePositions.map { sharableFileUris[it] }

        for (ip in selectedTargetIps) {
            for (uri in selectedUris) {
                val sendIntent = Intent(this, NetworkService::class.java).apply {
                    action = NetworkService.ACTION_SEND_FILE
                    putExtra(NetworkService.EXTRA_TARGET_IP, ip)
                    putExtra(NetworkService.EXTRA_FILE_URI, uri)
                }
                startService(sendIntent)
            }
        }

        val message = "Sending ${selectedUris.size} item(s) to ${selectedTargetIps.size} peer(s)..."
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()

        peersAdapter.clearSelections()
        filesAdapter.clearSelections()
    }

    private fun handleProgressUpdate(intent: Intent) {
        val isComplete = intent.getBooleanExtra(NetworkService.EXTRA_IS_COMPLETE, false)
        if (isComplete) {
            progressLayout.visibility = View.GONE
            return
        }
        progressLayout.visibility = View.VISIBLE
        val isSending = intent.getBooleanExtra(NetworkService.EXTRA_IS_SENDING, false)
        val bytes = intent.getLongExtra(NetworkService.EXTRA_BYTES_TRANSFERRED, 0)
        val total = intent.getLongExtra(NetworkService.EXTRA_TOTAL_BYTES, 1)
        val fileName = intent.getStringExtra(NetworkService.EXTRA_FILE_NAME) ?: ""
        val transferredMB = bytes / 1_000_000.0
        val totalMB = total / 1_000_000.0
        val actionText = if (isSending) "Sending" else "Receiving"

        val statusMessage = "$actionText: $fileName\n${String.format(Locale.US, "%.2f", transferredMB)} / ${String.format(Locale.US, "%.2f", totalMB)} MB"
        progressStatusText.text = statusMessage
        progressBar.max = 100
        if (total > 0) {
            val progress = (bytes * 100.0 / total).toInt()
            progressBar.progress = progress
        } else {
            progressBar.progress = 0
        }
    }

    private fun showQrCodeDialog() {
        val ipAddress = getLocalIpAddress()
        if (ipAddress == null) {
            Toast.makeText(this, "Could not get IP address. Make sure you are connected to Wi-Fi.", Toast.LENGTH_LONG).show()
            return
        }

        val qrCodeBitmap = generateQrCode(ipAddress)

        val dialog = Dialog(this)
        dialog.setContentView(R.layout.dialog_qr_code)
        val qrCodeImageView = dialog.findViewById<ImageView>(R.id.qrCodeImageView)
        qrCodeImageView.setImageBitmap(qrCodeBitmap)
        dialog.show()
    }

    private fun generateQrCode(text: String): Bitmap {
        val writer = QRCodeWriter()
        val bitMatrix = writer.encode(text, BarcodeFormat.QR_CODE, 512, 512)
        val width = bitMatrix.width
        val height = bitMatrix.height
        val bmp = createBitmap(width, height, Bitmap.Config.RGB_565)
        for (x in 0 until width) {
            for (y in 0 until height) {
                bmp[x, y] = if (bitMatrix[x, y]) Color.BLACK else Color.WHITE
            }
        }
        return bmp
    }

    private fun getLocalIpAddress(): String? {
        try {
            val wifiManager = getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            val ipInt = wifiManager.connectionInfo.ipAddress
            return if (ipInt == 0) null else String.format(
                Locale.US,
                "%d.%d.%d.%d",
                ipInt and 0xff,
                ipInt shr 8 and 0xff,
                ipInt shr 16 and 0xff,
                ipInt shr 24 and 0xff
            )
        } catch (_: Exception) {
            return null
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        LocalBroadcastManager.getInstance(this).unregisterReceiver(transferUpdateReceiver)
    }

    // --- Helper Functions ---
    private fun getFileName(uri: Uri): String {
        if (uri.scheme == "file") {
            return File(uri.path!!).name
        }
        if (DocumentsContract.isTreeUri(uri)) {
            val documentFile = DocumentFile.fromTreeUri(this, uri)
            return documentFile?.name ?: "Unknown Folder"
        }
        var name = "Unknown File"
        val cursor = contentResolver.query(uri, null, null, null, null)
        cursor?.use {
            if (it.moveToFirst()) {
                val nameIndex = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex != -1) name = it.getString(nameIndex)
            }
        }
        return name
    }

    private fun zipDirectory(dirUri: Uri): Uri? {
        try {
            val dirName = getFileName(dirUri)
            val zipFile = File(cacheDir, "$dirName.zip")
            val documentTree = DocumentFile.fromTreeUri(this, dirUri) ?: return null
            ZipOutputStream(FileOutputStream(zipFile)).use { zos ->
                addFolderToZip(documentTree, "", zos)
            }
            return zipFile.toUri()
        } catch (e: Exception) {
            e.printStackTrace()
            return null
        }
    }

    private fun addFolderToZip(directory: DocumentFile, parentPath: String, zos: ZipOutputStream) {
        directory.listFiles().forEach { file ->
            val currentPath = if (parentPath.isEmpty()) file.name!! else "$parentPath/${file.name}"
            if (file.isDirectory) {
                addFolderToZip(file, currentPath, zos)
            } else {
                zos.putNextEntry(ZipEntry(currentPath))
                contentResolver.openInputStream(file.uri)?.use { it.copyTo(zos) }
                zos.closeEntry()
            }
        }
    }
}
