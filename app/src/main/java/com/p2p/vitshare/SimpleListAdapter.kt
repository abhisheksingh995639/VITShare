package com.p2p.vitshare

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

class SimpleListAdapter(
    private val items: List<String>,
    private val onItemClick: (Int) -> Unit
) : RecyclerView.Adapter<SimpleListAdapter.ViewHolder>() {

    val selectedPositions = mutableSetOf<Int>()

    inner class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val fileNameTextView: TextView = view.findViewById(R.id.fileName)
        val checkIcon: ImageView = view.findViewById(R.id.checkIcon)

        init {
            itemView.setOnClickListener {
                val position = bindingAdapterPosition
                if (position != RecyclerView.NO_POSITION) {
                    toggleSelection(position)
                    onItemClick(position)
                }
            }
        }
    }

    private fun toggleSelection(position: Int) {
        if (selectedPositions.contains(position)) {
            selectedPositions.remove(position)
        } else {
            selectedPositions.add(position)
        }
        notifyItemChanged(position)
    }

    fun clearSelections() {
        val positionsToUpdate = selectedPositions.toList()
        selectedPositions.clear()
        positionsToUpdate.forEach { notifyItemChanged(it) }
    }

    fun setSelectedPosition(position: Int) {
        val positionsToUpdate = selectedPositions.toList()
        selectedPositions.clear()
        positionsToUpdate.forEach { notifyItemChanged(it) }

        selectedPositions.add(position)
        notifyItemChanged(position)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.list_item, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.fileNameTextView.text = items[position]
        if (selectedPositions.contains(position)) {
            holder.itemView.setBackgroundResource(R.color.selected_item_background)
            holder.checkIcon.visibility = View.VISIBLE
        } else {
            holder.itemView.setBackgroundResource(R.color.card_background)
            holder.checkIcon.visibility = View.GONE
        }
    }

    override fun getItemCount() = items.size
}